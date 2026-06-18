# execution/data/backfill.py
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from execution.data.paginate import iter_windows, stitch
from execution.data.normalize import from_questrade_candle
from execution.data.questrade_client import QuestradeClient, QuestradeAPIError, QuestradeAuthError

_CAP = 500          # Questrade per-request candle cap
_WINDOW_RETRIES = 3


class SeriesUnavailable(RuntimeError):
    """The whole (symbol, tf) series cannot be fetched from Questrade (systemic)."""


def _get_candles_retry(client, symbol_id, ws, we, interval, sleep):
    last = None
    for _ in range(_WINDOW_RETRIES):
        try:
            return client.get_candles(symbol_id, ws, we, interval=interval)
        except QuestradeAuthError:
            raise  # systemic — won't fix across retries; bubble up immediately
        except QuestradeAPIError as e:
            if getattr(e, "status", None) == 400:
                raise  # definitive (out-of-horizon / bad range) — retrying won't help
            last = e
            if sleep:
                time.sleep(sleep)
    raise last


def fetch_series_questrade(client, symbol: str, tf: str, start: datetime, end: datetime,
                           params: dict) -> tuple[list[dict], list[list[str]]]:
    """Paginate one (symbol, tf) series from Questrade.

    Returns (rows, gaps). A window that errors is recorded as a gap and the walk
    continues — Questrade only retains ~60-90 days of intraday, so old windows 400
    and must NOT doom the whole series (the recent windows still have data). Only an
    auth failure is systemic (raises SeriesUnavailable); a >=500-candle window raises
    RuntimeError (window too wide). An all-gap series returns ([], gaps); the caller
    decides what an empty series means.
    """
    wcfg = params["data"]["windows"][tf]
    interval, window_days = wcfg["interval"], wcfg["window_days"]
    sleep = params["data"]["request_sleep_sec"]
    symbol_id = client.find_symbol_id(symbol)

    per_window: list[list[dict]] = []
    gaps: list[list[str]] = []
    for ws, we in iter_windows(start, end, window_days):
        try:
            raw = _get_candles_retry(client, symbol_id, ws, we, interval, sleep)
        except QuestradeAuthError as e:
            raise SeriesUnavailable(f"{symbol} {tf}: auth failure: {e}") from e
        except QuestradeAPIError as e:
            gaps.append([ws.isoformat(), we.isoformat()])  # 400=no data this far back / transient
            continue
        if len(raw) >= _CAP:
            raise RuntimeError(
                f"{symbol} {tf} window {ws.isoformat()}..{we.isoformat()} returned "
                f"{len(raw)} candles (>= {_CAP} cap) — shrink data.windows.{tf}.window_days")
        per_window.append([from_questrade_candle(c) for c in raw])
        if sleep:
            time.sleep(sleep)
    return stitch(per_window), gaps


# ---------------------------------------------------------------------------
# Slice 7b — manifest + write_series
# ---------------------------------------------------------------------------


def _manifest_path(out_dir) -> Path:
    return Path(out_dir) / "manifest.json"


def load_manifest(out_dir) -> dict:
    p = _manifest_path(out_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_series(out_dir, symbol: str, tf: str, rows: list[dict], *,
                 source: str, gaps: list, status: str) -> None:
    """Write {SYMBOL}_{tf}.json (only if rows present) and upsert the manifest entry.

    A `failed`/empty series writes NO data file — never a silent stub — but DOES
    record the failure in the manifest so coverage is unambiguous.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if rows:
        (out / f"{symbol}_{tf}.json").write_text(json.dumps(rows))
    man = load_manifest(out_dir)
    man[f"{symbol}_{tf}"] = {
        "symbol": symbol, "tf": tf, "source": source, "status": status,
        "covered_start": rows[0]["ts"] if rows else None,
        "covered_end": rows[-1]["ts"] if rows else None,
        "row_count": len(rows), "gaps": gaps,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _manifest_path(out_dir).write_text(json.dumps(man, indent=2))


# ---------------------------------------------------------------------------
# Slice 7c — backfill_one (source selection + fallback + resume)
# ---------------------------------------------------------------------------

def _yf_fetch(symbol: str, tf: str, start: datetime, end: datetime) -> list[dict]:
    """Indirection so tests can stub the yfinance backup without importing pandas."""
    from execution.data import yfinance_client
    return yfinance_client.fetch(symbol, tf, start, end)


def _is_complete(out_dir, symbol: str, tf: str, start: datetime) -> bool:
    entry = load_manifest(out_dir).get(f"{symbol}_{tf}")
    if not entry or entry.get("status") != "ok" or not entry.get("covered_start"):
        return False
    covered = datetime.fromisoformat(entry["covered_start"])
    return covered <= start  # both tz-aware -> compared as instants


# Per-tf source preference, driven by real data horizons: Questrade retains only
# ~60-90d of intraday but full daily; yfinance gives ~730d of 1h but only ~60d of 5m.
#   5m -> Questrade only (deepest free 5m; no yfinance, which would silently truncate)
#   1h -> yfinance first (730d >> Questrade's ~90d), Questrade as backup
#   1d -> Questrade first (clean 2yr+), yfinance as backup
_SOURCES: dict[str, tuple[str, ...]] = {
    "5m": ("questrade",),
    "1h": ("yfinance", "questrade"),
    "1d": ("questrade", "yfinance"),
}


def _fetch_from_source(source, client, symbol, tf, start, end, params):
    """Fetch (rows, gaps) from one named source. Raises SeriesUnavailable on a
    systemic Questrade auth failure."""
    if source == "questrade":
        return fetch_series_questrade(client, symbol, tf, start, end, params)
    return _yf_fetch(symbol, tf, start, end), []


def backfill_one(client, symbol: str, tf: str, start: datetime, end: datetime,
                 params: dict, out_dir, force: bool = False) -> str:
    """Backfill one (symbol, tf) series, trying its sources in preference order.
    Returns 'ok' | 'partial' | 'failed' | 'skipped'."""
    if not force and _is_complete(out_dir, symbol, tf, start):
        return "skipped"
    wcfg = params["data"]["windows"][tf]
    horizon = wcfg.get("max_lookback_days")
    if horizon:  # don't request older than the source can serve (avoids empty-window churn)
        start = max(start, end - timedelta(days=horizon))

    sources = _SOURCES.get(tf, ("questrade",))
    source_errors: list[dict] = []
    for source in sources:
        try:
            rows, gaps = _fetch_from_source(source, client, symbol, tf, start, end, params)
        except SeriesUnavailable as e:
            source_errors.append({"source": source, "type": "SeriesUnavailable", "error": str(e)})
            print(f"[backfill] {symbol}_{tf} source={source} unavailable: {e}", flush=True)
            continue
        except Exception as e:  # noqa: BLE001 — a dead source shouldn't kill the series; try the next
            source_errors.append({"source": source, "type": type(e).__name__, "error": str(e)})
            print(f"[backfill] {symbol}_{tf} source={source} failed: {type(e).__name__}: {e}", flush=True)
            continue
        if rows:
            status = "partial" if gaps else "ok"
            write_series(out_dir, symbol, tf, rows, source=source, gaps=gaps, status=status)
            return status
        source_errors.append({"source": source, "type": "empty", "error": "zero rows returned"})
        print(f"[backfill] {symbol}_{tf} source={source} returned zero rows", flush=True)
    print(f"[backfill] {symbol}_{tf} failed all sources: {source_errors}", flush=True)
    write_series(out_dir, symbol, tf, [], source=sources[0], gaps=[], status="failed")
    return "failed"


# ---------------------------------------------------------------------------
# Slice 7d — backfill top loop + summary
# ---------------------------------------------------------------------------

def backfill(symbols, tfs, start: datetime, end: datetime, params: dict,
             *, out_dir, client=None, force: bool = False) -> dict:
    """Backfill every (symbol, tf). Returns {f'{symbol}_{tf}': status}."""
    client = client or QuestradeClient()
    summary: dict[str, str] = {}
    for symbol in symbols:
        for tf in tfs:
            key = f"{symbol}_{tf}"
            try:
                summary[key] = backfill_one(client, symbol, tf, start, end, params, out_dir, force)
            except Exception as e:  # noqa: BLE001 — isolate per-series; never abort the run
                summary[key] = f"error: {e}"
            print(f"{key}: {summary[key]}")
    return summary


# ---------------------------------------------------------------------------
# Slice 7e — CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from datetime import timedelta
    from execution.config import load_params
    from execution.data.env import load_dotenv

    load_dotenv()  # surface QUESTRADE_REFRESH_TOKEN from project-root .env
    p = load_params()
    d = p["data"]
    ap = argparse.ArgumentParser(description="Backfill Questrade bulk bars into the BarStore.")
    ap.add_argument("--symbols", nargs="*", default=[d["benchmark"], *d["universe"]])
    ap.add_argument("--tfs", nargs="*", default=d["timeframes"])
    ap.add_argument("--years", type=float, default=d["lookback_years"])
    ap.add_argument("--out", default=d["out_dir"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(a.years * 365))
    print(f"Backfilling {a.symbols} {a.tfs} {start.date()}..{end.date()} -> {a.out}")
    summary = backfill(a.symbols, a.tfs, start, end, p, out_dir=a.out, force=a.force)
    ok = sum(1 for v in summary.values() if v in ("ok", "skipped"))
    print(f"\nDone: {ok}/{len(summary)} ok/skipped. Full: {summary}")
