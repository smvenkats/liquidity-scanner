# execution/scanner/run_scan.py
"""One scan cycle for the hosted dashboard: refresh data, scan today's session, and append
only signals not already emitted. Pure scanner layer — no dashboard dependency."""
from __future__ import annotations
import json
from pathlib import Path

from execution.scanner.engine import scan_once
from execution.scanner.sink import emit_signals
from execution.scanner.tiers import annotate_trend, dedupe_setups


def existing_signal_ids(signals_path) -> set:
    p = Path(signals_path)
    if not p.exists():
        return set()
    ids = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line).get("signal_id"))
        except json.JSONDecodeError:
            continue
    return ids


def filter_fresh(signals, signals_path) -> list:
    """Signals whose signal_id is not already present in signals_path (cross-run dedup)."""
    seen = existing_signal_ids(signals_path)
    return [s for s in signals if s.signal_id not in seen]


def run_scan(params, *, out_dir, signals_path, benchmark="SPY", do_backfill=True) -> int:
    """Refresh data (optional), scan today's session (core-passing = gate off, incl. reversals),
    annotate the real 1h trend, append only fresh signals to signals_path. Returns fresh count."""
    from execution.backtest.store import BarStore
    if do_backfill:
        from datetime import datetime, timedelta, timezone
        from execution.data.backfill import backfill
        d = params["data"]
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(d["lookback_years"] * 365))
        print(f"[scan] backfill_start out_dir={out_dir} symbols={len([d['benchmark'], *d['universe']])} "
              f"tfs={d['timeframes']} start={start.date()} end={end.date()}", flush=True)
        summary = backfill([d["benchmark"], *d["universe"]], d["timeframes"], start, end, params, out_dir=out_dir)
        failed = {k: v for k, v in summary.items() if v not in ("ok", "partial", "skipped")}
        print(f"[scan] backfill_done ok_partial_skipped={len(summary) - len(failed)}/{len(summary)} "
              f"failed={failed}", flush=True)

    store = BarStore(out_dir)
    bench5 = store.bars(benchmark, "5m")
    print(f"[scan] benchmark={benchmark} bench5_rows={len(bench5)}", flush=True)
    if not bench5:
        print("[scan] abort=no_benchmark_5m", flush=True)
        return 0
    print(f"[scan] benchmark_latest_5m={bench5[-1].ts.isoformat()}", flush=True)
    as_of = max(b.ts.date() for b in bench5)
    sigs = scan_once(params["data"]["universe"], store, {}, params=params,
                     benchmark=benchmark, trend_gate=False, mode="live", as_of_date=as_of)
    print(f"[scan] scan_once_raw={len(sigs)} as_of={as_of}", flush=True)
    sigs = dedupe_setups(sigs)              # one per (symbol, level, direction) — match the CLI feed
    after_dedupe = len(sigs)
    annotate_trend(sigs, store, params)
    fresh = filter_fresh(sigs, signals_path)
    print(f"[scan] after_setup_dedupe={after_dedupe} fresh={len(fresh)} "
          f"existing_signal_ids={len(existing_signal_ids(signals_path))}", flush=True)
    emit_signals(fresh, signals_path)
    return len(fresh)


if __name__ == "__main__":
    import os
    from execution.config import load_params
    from execution.data.env import load_dotenv

    load_dotenv()
    p = load_params()
    out = os.environ.get("BARS_DIR", p["data"]["out_dir"])
    sigs_path = os.environ.get("SIGNALS_PATH", ".tmp/signals.jsonl")
    n = run_scan(p, out_dir=out, signals_path=sigs_path, benchmark=p["data"]["benchmark"])
    print(f"emitted {n} fresh signals -> {sigs_path}")
