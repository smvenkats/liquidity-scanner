# Questrade Bulk Data Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill 2 years of 5m/1h/1d bars for SPY + ~10 liquid names into the `BarStore` file format via time-windowed Questrade pagination (with yfinance backup for 1h/1d), so `gate_lift` can finally be run on statistically meaningful data.

**Architecture:** A self-contained `execution/data/` layer. Pure logic (`paginate`, `normalize`) is unit-tested with zero network; I/O clients (`questrade_client` ported from the proven odte project, `yfinance_client`) are isolated; `backfill` orchestrates per-`(symbol, tf)` series with source selection, fallback, gap recording, and a `manifest.json`. The detection/backtest engine is untouched — `BarStore(root="data/bars")` consumes the output as-is.

**Tech Stack:** Python 3.x, pytest (`pythonpath=["."]`), pyyaml, curl_cffi (Cloudflare transport), yfinance + pandas (1h/1d backup).

---

> **⚠️ COMMIT POLICY (project rule overrides the skill default):** The user's standing rule is **no commits/pushes until the phase is locally tested AND the user signs off.** Therefore: do **NOT** commit per task. Each task ends by running the test suite green. Hold all commits until the entire plan is green and the user approves — then make ONE phase commit + push (Task 9). Treat each task's verification as "tests green," not "committed."

> **Reference for the port:** `C:\Users\smven\odte-vwap-scanner\execution\scanner\questrade_provider.py` is the proven source for Task 5. Read it before that task.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `execution/data/__init__.py` | package marker |
| `execution/data/paginate.py` | PURE: tf→interval map, `iter_windows`, `stitch` (dedup+sort) |
| `execution/data/normalize.py` | PURE: Questrade candle & yfinance row → `{ts,o,h,l,c,v}` |
| `execution/data/questrade_client.py` | PORTED I/O: OAuth+rotation+cache, transport ladder, `find_symbol_id`, `get_candles` |
| `execution/data/yfinance_client.py` | Backup I/O for 1h/1d only; horizon-clamped |
| `execution/data/backfill.py` | Orchestrator + `__main__` CLI: per-series fetch, fallback, manifest, resumability |
| `directives/fetch_bulk_data.md` | SOP |
| `execution/params.yaml` | `data:` config block (modify) |
| `requirements.txt` | add `curl_cffi`, `yfinance` (modify) |
| `.gitignore` | ignore `.env`, `.questrade_token.json`, `data/bars/` (modify) |

---

## Task 0: Config, deps, gitignore

**Files:**
- Modify: `requirements.txt`
- Modify: `execution/params.yaml`
- Modify: `.gitignore`
- Create: `execution/data/__init__.py`
- Test: `tests/test_data_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_config.py
from execution.config import load_params

def test_data_block_present_and_shaped():
    p = load_params()
    d = p["data"]
    assert d["out_dir"] == "data/bars"
    assert d["benchmark"] == "SPY"
    assert "QQQ" in d["universe"] and len(d["universe"]) >= 8
    assert d["timeframes"] == ["5m", "1h", "1d"]
    assert d["lookback_years"] == 2
    assert d["windows"]["5m"] == {"interval": "FiveMinutes", "window_days": 2}
    assert d["windows"]["1h"]["window_days"] == 25
    assert d["windows"]["1d"]["window_days"] == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_config.py -v`
Expected: FAIL with `KeyError: 'data'`

- [ ] **Step 3: Append the `data:` block to `execution/params.yaml`**

```yaml
data:
  out_dir: "data/bars"
  benchmark: "SPY"
  universe: [QQQ, AAPL, NVDA, TSLA, AMD, META, AMZN, MSFT, GOOGL, NFLX]
  timeframes: ["5m", "1h", "1d"]
  lookback_years: 2
  request_sleep_sec: 0.2
  windows:
    "5m": { interval: "FiveMinutes", window_days: 2 }
    "1h": { interval: "OneHour",     window_days: 25 }
    "1d": { interval: "OneDay",      window_days: 400 }
```

- [ ] **Step 4: Add deps to `requirements.txt`**

Append:
```
curl_cffi>=0.7
yfinance>=0.2.40
```

- [ ] **Step 5: Update `.gitignore`** (append if not already present)

```
.env
.questrade_token.json
data/bars/
```

- [ ] **Step 6: Create the package marker**

```python
# execution/data/__init__.py
```
(empty file)

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/test_data_config.py -v`
Expected: PASS

---

## Task 1: paginate — interval map

**Files:**
- Create: `execution/data/paginate.py`
- Test: `tests/test_data_paginate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_paginate.py
import pytest
from execution.data.paginate import interval_for_tf

def test_interval_for_tf_maps_known():
    assert interval_for_tf("5m") == "FiveMinutes"
    assert interval_for_tf("1h") == "OneHour"
    assert interval_for_tf("1d") == "OneDay"

def test_interval_for_tf_rejects_unknown():
    with pytest.raises(ValueError):
        interval_for_tf("3m")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `execution/data/paginate.py`**

```python
# execution/data/paginate.py
from __future__ import annotations
from datetime import datetime, timedelta

_INTERVALS = {"5m": "FiveMinutes", "1h": "OneHour", "1d": "OneDay"}


def interval_for_tf(tf: str) -> str:
    try:
        return _INTERVALS[tf]
    except KeyError:
        raise ValueError(f"unsupported timeframe: {tf!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: PASS

---

## Task 2: paginate — iter_windows

**Files:**
- Modify: `execution/data/paginate.py`
- Test: `tests/test_data_paginate.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from datetime import datetime, timezone
from execution.data.paginate import iter_windows

def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)

def test_iter_windows_splits_range():
    w = iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 6), window_days=2)
    assert w == [(_dt(2026, 1, 1), _dt(2026, 1, 3)),
                 (_dt(2026, 1, 3), _dt(2026, 1, 5)),
                 (_dt(2026, 1, 5), _dt(2026, 1, 6))]

def test_iter_windows_range_smaller_than_window():
    w = iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 2), window_days=400)
    assert w == [(_dt(2026, 1, 1), _dt(2026, 1, 2))]

def test_iter_windows_empty_when_start_ge_end():
    assert iter_windows(_dt(2026, 1, 2), _dt(2026, 1, 1), window_days=2) == []

def test_iter_windows_rejects_nonpositive_window():
    with pytest.raises(ValueError):
        iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 2), window_days=0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: FAIL with `ImportError: cannot import name 'iter_windows'`

- [ ] **Step 3: Append to `execution/data/paginate.py`**

```python
def iter_windows(start: datetime, end: datetime,
                 window_days: int) -> list[tuple[datetime, datetime]]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    out: list[tuple[datetime, datetime]] = []
    cur = start
    span = timedelta(days=window_days)
    while cur < end:
        nxt = min(cur + span, end)
        out.append((cur, nxt))
        cur = nxt
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: PASS

---

## Task 3: paginate — stitch

**Files:**
- Modify: `execution/data/paginate.py`
- Test: `tests/test_data_paginate.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from execution.data.paginate import stitch

def _row(ts, c):
    return {"ts": ts, "o": c, "h": c, "l": c, "c": c, "v": 1}

def test_stitch_dedups_by_ts_and_sorts():
    a = [_row("2026-01-02T13:30:00+00:00", 1), _row("2026-01-02T13:35:00+00:00", 2)]
    b = [_row("2026-01-02T13:35:00+00:00", 2), _row("2026-01-02T13:40:00+00:00", 3)]  # boundary overlap
    out = stitch([a, b])
    assert [r["ts"] for r in out] == [
        "2026-01-02T13:30:00+00:00",
        "2026-01-02T13:35:00+00:00",
        "2026-01-02T13:40:00+00:00",
    ]
    assert len(out) == 3

def test_stitch_handles_empty():
    assert stitch([[], []]) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: FAIL with `ImportError: cannot import name 'stitch'`

- [ ] **Step 3: Append to `execution/data/paginate.py`**

```python
def stitch(window_results: list[list[dict]], *, key: str = "ts") -> list[dict]:
    """Flatten paginated windows into one series: dedup by `key`, sort ascending."""
    seen: dict[str, dict] = {}
    for rows in window_results:
        for r in rows:
            seen[r[key]] = r  # identical at boundaries; last write wins
    return sorted(seen.values(), key=lambda r: r[key])
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_paginate.py -v`
Expected: PASS

---

## Task 4: normalize — Questrade & yfinance rows

**Files:**
- Create: `execution/data/normalize.py`
- Test: `tests/test_data_normalize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_normalize.py
import pytest
from execution.data.normalize import from_questrade_candle, from_yf_record

def test_from_questrade_candle_maps_fields():
    c = {"start": "2024-01-02T09:30:00.000000-05:00", "open": "1.5",
         "high": 2, "low": 1, "close": 1.75, "volume": 1000}
    assert from_questrade_candle(c) == {
        "ts": "2024-01-02T09:30:00.000000-05:00",
        "o": 1.5, "h": 2.0, "l": 1.0, "c": 1.75, "v": 1000.0,
    }

def test_from_questrade_candle_missing_field_raises():
    with pytest.raises(KeyError):
        from_questrade_candle({"start": "x", "open": 1, "high": 2, "low": 1, "close": 1})

def test_from_yf_record_maps_fields():
    rec = {"ts": "2024-01-02T10:00:00-05:00", "Open": 1, "High": 2,
           "Low": 0.5, "Close": 1.5, "Volume": 50}
    assert from_yf_record(rec) == {
        "ts": "2024-01-02T10:00:00-05:00",
        "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 50.0,
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `execution/data/normalize.py`**

```python
# execution/data/normalize.py
from __future__ import annotations


def from_questrade_candle(c: dict) -> dict:
    """Questrade candle {start,open,high,low,close,volume} -> BarStore row.

    `start` is kept verbatim — Questrade returns it as an exchange-tz ISO string,
    which is what session-grouping (ts.date()) expects.
    """
    return {"ts": c["start"], "o": float(c["open"]), "h": float(c["high"]),
            "l": float(c["low"]), "c": float(c["close"]), "v": float(c["volume"])}


def from_yf_record(rec: dict) -> dict:
    """yfinance record {ts, Open, High, Low, Close, Volume} -> BarStore row."""
    return {"ts": rec["ts"], "o": float(rec["Open"]), "h": float(rec["High"]),
            "l": float(rec["Low"]), "c": float(rec["Close"]), "v": float(rec["Volume"])}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_normalize.py -v`
Expected: PASS

---

## Task 5: Port the Questrade client

**Files:**
- Create: `execution/data/questrade_client.py`
- Test: `tests/test_data_questrade_client.py`

**Action:** Copy the proven client from odte, stripped to a pure market-data client (no order methods — `read_md` only).

- [ ] **Step 1: Create `execution/data/questrade_client.py`** by copying
`C:\Users\smven\odte-vwap-scanner\execution\scanner\questrade_provider.py` and applying these exact edits:
  1. **Delete** the three odte-specific imports: `import config`, `from data_provider import DataProvider`, `from models import Bar`.
  2. **Delete** the line `ET = ZoneInfo(config.TIMEZONE)` and the now-unused `from zoneinfo import ZoneInfo` import.
  3. **Replace** the `DEFAULT_TOKEN_CACHE` definition with:
     ```python
     DEFAULT_TOKEN_CACHE = Path(__file__).resolve().parents[2] / ".questrade_token.json"
     ```
     (`parents[2]` = project root: `execution/data/questrade_client.py` → root.)
  4. **Delete** the entire `class QuestradeDataProvider(DataProvider):` block (odte lines ~374–401) and the `if __name__ == "__main__":` smoke block (odte lines ~404–418) — they depend on the deleted `Bar`/`config`. We add our own smoke later.
  5. Keep everything else verbatim: `QuestradeAuthError`, `QuestradeAPIError`, the transport ladder (`_urllib_request_json`, `_curl_cffi_request_json`, `_cloudscraper_request_json`, `_http_request_json`), and `class QuestradeClient` with `find_symbol_id` and `get_candles`.

- [ ] **Step 2: Write regression tests guarding the port**

```python
# tests/test_data_questrade_client.py
import json
import pytest
from execution.data import questrade_client as qc


def test_build_url_inserts_single_v1():
    u = qc.QuestradeClient._build_url("https://api01.iq.questrade.com", "/markets/candles/9", None)
    assert u == "https://api01.iq.questrade.com/v1/markets/candles/9"
    u2 = qc.QuestradeClient._build_url("https://api01.iq.questrade.com/v1", "/x", {"a": 1})
    assert u2 == "https://api01.iq.questrade.com/v1/x?a=1"


def test_cached_refresh_token_supersedes_env(tmp_path):
    cache = tmp_path / "tok.json"
    cache.write_text(json.dumps({"refresh_token": "ROTATED", "access_token": "A",
                                 "api_server": "https://s", "expires_at": 0.0}))
    client = qc.QuestradeClient(refresh_token="ENV_SEED", token_cache_path=cache)
    assert client._current_refresh_token() == "ROTATED"


def test_get_candles_parses_list(monkeypatch):
    client = qc.QuestradeClient(refresh_token="x", token_cache_path="/nonexistent.json")
    monkeypatch.setattr(client, "_authorized_get",
                        lambda path, params=None: {"candles": [{"start": "t", "open": 1}]})
    from datetime import datetime, timezone
    out = client.get_candles(9, datetime(2026, 1, 1, tzinfo=timezone.utc),
                             datetime(2026, 1, 2, tzinfo=timezone.utc), interval="FiveMinutes")
    assert out == [{"start": "t", "open": 1}]


def test_transport_dispatch_forces_curl_cffi(monkeypatch):
    monkeypatch.setenv("QUESTRADE_HTTP_TRANSPORT", "curl_cffi")
    monkeypatch.setattr(qc, "_curl_cffi_request_json", lambda *a, **k: {"via": "curl_cffi"})
    assert qc._http_request_json("https://x") == {"via": "curl_cffi"}
```

- [ ] **Step 3: Run to verify the port works**

Run: `python -m pytest tests/test_data_questrade_client.py -v`
Expected: PASS (all 4). If `test_build_url` fails, the `_build_url` staticmethod wasn't ported intact.

---

## Task 6: yfinance backup client (1h/1d only)

**Files:**
- Create: `execution/data/yfinance_client.py`
- Test: `tests/test_data_yfinance_client.py`

**Design:** `fetch()` does timeframe validation, Yahoo-horizon clamping, and normalization. The actual
Yahoo download is isolated in `_raw_download()` (returns a list of plain dicts), so tests monkeypatch it
without constructing pandas frames. `_raw_download` itself is exercised only by the live smoke (Task 8b).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_yfinance_client.py
import pytest
from datetime import datetime, timezone
from execution.data import yfinance_client as yfc


def test_fetch_rejects_5m():
    with pytest.raises(ValueError):
        yfc.fetch("SPY", "5m", datetime(2024, 1, 1, tzinfo=timezone.utc),
                  datetime(2024, 1, 2, tzinfo=timezone.utc))


def test_fetch_normalizes_and_passes_interval(monkeypatch):
    captured = {}

    def fake_dl(symbol, start, end, interval):
        captured.update(symbol=symbol, interval=interval, start=start, end=end)
        return [{"ts": "2024-01-02T10:00:00-05:00", "Open": 1, "High": 2,
                 "Low": 0.5, "Close": 1.5, "Volume": 9}]

    monkeypatch.setattr(yfc, "_raw_download", fake_dl)
    rows = yfc.fetch("SPY", "1h", datetime(2024, 1, 1, tzinfo=timezone.utc),
                     datetime(2024, 1, 3, tzinfo=timezone.utc))
    assert rows == [{"ts": "2024-01-02T10:00:00-05:00", "o": 1.0, "h": 2.0,
                     "l": 0.5, "c": 1.5, "v": 9.0}]
    assert captured["interval"] == "60m"


def test_fetch_clamps_1h_to_730_days(monkeypatch):
    captured = {}
    monkeypatch.setattr(yfc, "_raw_download",
                        lambda symbol, start, end, interval: captured.update(start=start) or [])
    end = datetime(2024, 6, 1, tzinfo=timezone.utc)
    far_start = datetime(2020, 1, 1, tzinfo=timezone.utc)  # ~1600 days back
    yfc.fetch("SPY", "1h", far_start, end)
    # clamped to within ~730 days of end, not the original far_start
    assert (end - captured["start"]).days <= 730
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_yfinance_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `execution/data/yfinance_client.py`**

```python
# execution/data/yfinance_client.py
"""yfinance backup source. 1h/1d ONLY — Yahoo caps intraday history (~60d for 5m),
so 5m is never sourced here (it would silently truncate the research series)."""
from __future__ import annotations
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from execution.data.normalize import from_yf_record

ET = ZoneInfo("America/New_York")
_YF_INTERVAL = {"1h": "60m", "1d": "1d"}
_MAX_DAYS = {"1h": 730, "1d": None}  # Yahoo horizon caps (None = full history)


def _raw_download(symbol: str, start: datetime, end: datetime, interval: str) -> list[dict]:
    """Real Yahoo download isolated for testability. Returns plain records
    {ts(iso, ET), Open, High, Low, Close, Volume}. Not unit-tested (see live smoke)."""
    import yfinance as yf
    df = yf.download(symbol, start=start.date().isoformat(), end=end.date().isoformat(),
                     interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return []
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.droplevel(axis=1, level=1)  # single-ticker MultiIndex -> flat
    out = []
    for idx, row in df.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ET)
        out.append({"ts": ts.astimezone(ET).isoformat(),
                    "Open": row["Open"], "High": row["High"], "Low": row["Low"],
                    "Close": row["Close"], "Volume": row["Volume"]})
    return out


def fetch(symbol: str, tf: str, start: datetime, end: datetime) -> list[dict]:
    if tf not in _YF_INTERVAL:
        raise ValueError(f"yfinance backup supports only 1h/1d, got {tf!r}")
    cap = _MAX_DAYS[tf]
    if cap is not None:
        earliest = end - timedelta(days=cap)
        if start < earliest:
            warnings.warn(f"yfinance {tf}: clamping start {start.date()} -> {earliest.date()} "
                          f"(Yahoo {cap}-day horizon)")
            start = earliest
    raw = _raw_download(symbol, start, end, _YF_INTERVAL[tf])
    return [from_yf_record(r) for r in raw]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_yfinance_client.py -v`
Expected: PASS (3)

---

## Task 7: backfill orchestrator

**Files:**
- Create: `execution/data/backfill.py`
- Test: `tests/test_data_backfill.py`

This task builds the orchestrator in four testable layers, then the CLI.

### 7a: `fetch_series_questrade` (paginate + guard + gaps)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_backfill.py
import json
import pytest
from datetime import datetime, timezone
from execution.data import backfill as bf


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class FakeClient:
    """Stand-in for QuestradeClient. `responses` maps window-start-day -> candle list.
    Days listed in `fail_days` raise to simulate per-window failure."""
    def __init__(self, responses, fail_days=()):
        self.responses = responses
        self.fail_days = set(fail_days)

    def find_symbol_id(self, symbol):
        return 1

    def get_candles(self, symbol_id, start, end, interval="OneDay"):
        if start.day in self.fail_days:
            raise bf.QuestradeAPIError("boom", status=503)
        return self.responses.get(start.day, [])


def _candle(ts, c=1):
    return {"start": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1}


def test_fetch_series_paginates_and_stitches():
    # 1d windows of 400 days -> one window for a 2-day span
    client = FakeClient({1: [_candle("2026-01-01T00:00:00+00:00"),
                             _candle("2026-01-02T00:00:00+00:00")]})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"1d": {"interval": "OneDay", "window_days": 400}}}}
    rows, gaps = bf.fetch_series_questrade(client, "ABC", "1d", _dt(2026, 1, 1), _dt(2026, 1, 3), params)
    assert [r["ts"] for r in rows] == ["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]
    assert gaps == []


def test_fetch_series_guard_trips_over_500():
    big = [_candle(f"2026-01-01T00:{i:02d}:00+00:00") for i in range(500)]
    client = FakeClient({1: big})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"1d": {"interval": "OneDay", "window_days": 400}}}}
    with pytest.raises(RuntimeError, match="500"):
        bf.fetch_series_questrade(client, "ABC", "1d", _dt(2026, 1, 1), _dt(2026, 1, 3), params)


def test_fetch_series_first_window_failure_raises_unavailable():
    client = FakeClient({}, fail_days={1})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2}}}}
    with pytest.raises(bf.SeriesUnavailable):
        bf.fetch_series_questrade(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 10), params)


def test_fetch_series_later_window_failure_records_gap():
    # 2-day windows over a 6-day span -> windows starting day 1, 3, 5. Fail day 3.
    client = FakeClient({1: [_candle("2026-01-01T13:30:00+00:00")],
                         5: [_candle("2026-01-05T13:30:00+00:00")]}, fail_days={3})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2}}}}
    rows, gaps = bf.fetch_series_questrade(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 7), params)
    assert len(rows) == 2
    assert len(gaps) == 1 and gaps[0][0].startswith("2026-01-03")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `execution/data/backfill.py` (first slice)**

```python
# execution/data/backfill.py
from __future__ import annotations
import time
from datetime import datetime

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
        except (QuestradeAPIError, QuestradeAuthError) as e:
            last = e
            if sleep:
                time.sleep(sleep)
    raise last


def fetch_series_questrade(client, symbol: str, tf: str, start: datetime, end: datetime,
                           params: dict) -> tuple[list[dict], list[list[str]]]:
    """Paginate one (symbol, tf) series from Questrade.

    Returns (rows, gaps). `gaps` is a list of [window_start_iso, window_end_iso] for
    windows that failed after retries. Raises SeriesUnavailable if the FIRST window
    fails (systemic), or RuntimeError if any window breaches the 500-candle cap.
    """
    wcfg = params["data"]["windows"][tf]
    interval, window_days = wcfg["interval"], wcfg["window_days"]
    sleep = params["data"]["request_sleep_sec"]
    symbol_id = client.find_symbol_id(symbol)

    per_window: list[list[dict]] = []
    gaps: list[list[str]] = []
    for i, (ws, we) in enumerate(iter_windows(start, end, window_days)):
        try:
            raw = _get_candles_retry(client, symbol_id, ws, we, interval, sleep)
        except (QuestradeAPIError, QuestradeAuthError) as e:
            if i == 0:
                raise SeriesUnavailable(f"{symbol} {tf}: first window failed: {e}") from e
            gaps.append([ws.isoformat(), we.isoformat()])
            continue
        if len(raw) >= _CAP:
            raise RuntimeError(
                f"{symbol} {tf} window {ws.isoformat()}..{we.isoformat()} returned "
                f"{len(raw)} candles (>= {_CAP} cap) — shrink data.windows.{tf}.window_days")
        per_window.append([from_questrade_candle(c) for c in raw])
        if sleep:
            time.sleep(sleep)
    return stitch(per_window), gaps
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_backfill.py -v`
Expected: PASS (4)

### 7b: manifest + `write_series`

- [ ] **Step 1: Write the failing test (append to `tests/test_data_backfill.py`)**

```python
def test_write_series_writes_file_and_manifest(tmp_path):
    rows = [{"ts": "2026-01-01T13:30:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
            {"ts": "2026-01-02T13:30:00+00:00", "o": 2, "h": 2, "l": 2, "c": 2, "v": 2}]
    bf.write_series(tmp_path, "ABC", "1d", rows, source="questrade", gaps=[], status="ok")
    data = json.loads((tmp_path / "ABC_1d.json").read_text())
    assert len(data) == 2
    man = json.loads((tmp_path / "manifest.json").read_text())
    entry = man["ABC_1d"]
    assert entry["source"] == "questrade"
    assert entry["covered_start"] == "2026-01-01T13:30:00+00:00"
    assert entry["covered_end"] == "2026-01-02T13:30:00+00:00"
    assert entry["row_count"] == 2 and entry["status"] == "ok"


def test_write_series_failed_writes_no_data_file(tmp_path):
    bf.write_series(tmp_path, "ABC", "5m", [], source="questrade", gaps=[], status="failed")
    assert not (tmp_path / "ABC_5m.json").exists()
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["ABC_5m"]["status"] == "failed" and man["ABC_5m"]["row_count"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_backfill.py -k write_series -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'write_series'`

- [ ] **Step 3: Append to `execution/data/backfill.py`**

```python
import json
from datetime import timezone
from pathlib import Path


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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_backfill.py -k write_series -v`
Expected: PASS (2)

### 7c: `backfill_one` (source selection + fallback + resume)

- [ ] **Step 1: Write the failing test (append)**

```python
def _params():
    return {"data": {"request_sleep_sec": 0, "out_dir": "ignored",
                     "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2},
                                 "1h": {"interval": "OneHour", "window_days": 25},
                                 "1d": {"interval": "OneDay", "window_days": 400}}}}


def test_backfill_one_5m_systemic_failure_marks_failed_no_file(tmp_path):
    client = FakeClient({}, fail_days={1})  # first 5m window fails
    status = bf.backfill_one(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 10),
                             _params(), tmp_path)
    assert status == "failed"
    assert not (tmp_path / "ABC_5m.json").exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["ABC_5m"]["status"] == "failed"


def test_backfill_one_1h_systemic_failure_falls_back_to_yfinance(tmp_path, monkeypatch):
    client = FakeClient({}, fail_days={1})  # questrade 1h unavailable
    monkeypatch.setattr(bf, "_yf_fetch",
                        lambda symbol, tf, start, end: [
                            {"ts": "2026-01-02T10:00:00-05:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}])
    status = bf.backfill_one(client, "ABC", "1h", _dt(2026, 1, 1), _dt(2026, 1, 10),
                             _params(), tmp_path)
    assert status == "ok"
    man = json.loads((tmp_path / "manifest.json").read_text())["ABC_1h"]
    assert man["source"] == "yfinance" and man["row_count"] == 1


def test_backfill_one_skips_when_complete(tmp_path):
    # Pre-seed a complete manifest entry; backfill_one must not call the client.
    bf.write_series(tmp_path, "ABC", "1d",
                    [{"ts": "2025-01-01T00:00:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
                    source="questrade", gaps=[], status="ok")

    class Boom:
        def find_symbol_id(self, s): raise AssertionError("should not be called")
        def get_candles(self, *a, **k): raise AssertionError("should not be called")

    status = bf.backfill_one(Boom(), "ABC", "1d", _dt(2025, 6, 1), _dt(2025, 6, 2),
                             _params(), tmp_path, force=False)
    assert status == "skipped"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_backfill.py -k backfill_one -v`
Expected: FAIL with `AttributeError: ... 'backfill_one'`

- [ ] **Step 3: Append to `execution/data/backfill.py`**

```python
def _yf_fetch(symbol: str, tf: str, start: datetime, end: datetime) -> list[dict]:
    """Indirection so tests can stub the yfinance backup without importing pandas."""
    from execution.data import yfinance_client
    return yfinance_client.fetch(symbol, tf, start, end)


def _is_complete(out_dir, symbol: str, tf: str, start: datetime) -> bool:
    entry = load_manifest(out_dir).get(f"{symbol}_{tf}")
    if not entry or entry.get("status") != "ok" or not entry.get("covered_start"):
        return False
    return entry["covered_start"] <= start.isoformat()


def backfill_one(client, symbol: str, tf: str, start: datetime, end: datetime,
                 params: dict, out_dir, force: bool = False) -> str:
    """Backfill one (symbol, tf) series. Returns 'ok' | 'partial' | 'failed' | 'skipped'."""
    if not force and _is_complete(out_dir, symbol, tf, start):
        return "skipped"
    try:
        rows, gaps = fetch_series_questrade(client, symbol, tf, start, end, params)
    except SeriesUnavailable:
        if tf == "5m":
            write_series(out_dir, symbol, tf, [], source="questrade", gaps=[], status="failed")
            return "failed"
        rows = _yf_fetch(symbol, tf, start, end)  # 1h/1d backup
        status = "ok" if rows else "failed"
        write_series(out_dir, symbol, tf, rows, source="yfinance", gaps=[], status=status)
        return status
    status = "partial" if gaps else "ok"
    write_series(out_dir, symbol, tf, rows, source="questrade", gaps=gaps, status=status)
    return status
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_backfill.py -k backfill_one -v`
Expected: PASS (3)

### 7d: `backfill` top loop + summary

- [ ] **Step 1: Write the failing test (append)**

```python
def test_backfill_loops_and_summarizes(tmp_path):
    client = FakeClient({1: [_candle("2026-01-01T00:00:00+00:00")]})
    summary = bf.backfill(["ABC"], ["1d"], _dt(2026, 1, 1), _dt(2026, 1, 2),
                          _params(), out_dir=tmp_path)
    assert summary == {"ABC_1d": "ok"}
    assert (tmp_path / "ABC_1d.json").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_data_backfill.py -k loops_and_summarizes -v`
Expected: FAIL with `AttributeError: ... 'backfill'`

- [ ] **Step 3: Append to `execution/data/backfill.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_data_backfill.py -k loops_and_summarizes -v`
Expected: PASS

### 7e: CLI entry point

- [ ] **Step 1: Append the `__main__` CLI to `execution/data/backfill.py`**

```python
if __name__ == "__main__":
    import argparse
    from datetime import timedelta
    from execution.config import load_params

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
```

- [ ] **Step 2: Verify the module imports and CLI parses (no network)**

Run: `python -c "import execution.data.backfill as b; print(hasattr(b, 'backfill'))"`
Expected: prints `True`

- [ ] **Step 3: Run the full data-layer suite**

Run: `python -m pytest tests/test_data_*.py -v`
Expected: ALL PASS

---

## Task 8: Directive + live smoke

### 8a: directive

- [ ] **Step 1: Create `directives/fetch_bulk_data.md`**

```markdown
# Directive: Fetch Bulk Historical Bars

**Goal:** Populate `data/bars/` with deep history so the backtest is statistically meaningful.

**Prerequisite (user does this, once):** Paste a fresh Questrade refresh token into
`liquidity-scanner/.env` as `QUESTRADE_REFRESH_TOKEN` (generate from a SEPARATE Questrade
personal app to avoid rotating the tv-mcp/odte token chains). Install deps:
`pip install -r requirements.txt`.

**Run:**
`python -m execution.data.backfill`            # uses params.yaml data block (SPY + universe, 2yr)
`python -m execution.data.backfill --symbols SPY AAPL --tfs 5m --years 1 --force`  # ad hoc

**Tools:** `execution/data/backfill.py` (orchestrator), `questrade_client.py` (primary),
`yfinance_client.py` (1h/1d backup). Config: `execution/params.yaml` `data:` block.

**Output:** `data/bars/{SYMBOL}_{tf}.json` (normalized {ts,o,h,l,c,v}) + `data/bars/manifest.json`
(source/coverage/gaps per series). Consume via `BarStore(root="data/bars")`.

**Edge cases / learnings:**
- 5m is Questrade-only and hard-fails loud (no yfinance fallback — Yahoo caps 5m at ~60d).
- If a window returns >=500 candles the run raises: shrink `data.windows.<tf>.window_days`.
- Questrade tokens are single-use-rotating; the client caches the rotated token in
  `.questrade_token.json`. A 400 on token exchange = stale/used token, regenerate it.
- Reruns skip series already complete in the manifest; use `--force` to refetch.
```

### 8b: live smoke (gated on token)

- [ ] **Step 1: Create `tests/test_data_live_smoke.py`**

```python
# tests/test_data_live_smoke.py
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

_HAS_TOKEN = bool(os.environ.get("QUESTRADE_REFRESH_TOKEN")) or \
    (Path(__file__).resolve().parents[1] / ".questrade_token.json").exists()


@pytest.mark.skipif(not _HAS_TOKEN, reason="no Questrade token configured")
def test_live_fetch_recent_spy_5m():
    from execution.data.questrade_client import QuestradeClient
    from execution.data.backfill import fetch_series_questrade
    from execution.config import load_params

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=3)
    rows, gaps = fetch_series_questrade(QuestradeClient(), "SPY", "5m", start, end, load_params())
    assert rows, "expected some recent SPY 5m bars"
    tss = [r["ts"] for r in rows]
    assert tss == sorted(tss), "bars must be ascending"
    assert set(rows[0]) == {"ts", "o", "h", "l", "c", "v"}
```

- [ ] **Step 2: Run the smoke (skips cleanly if no token)**

Run: `python -m pytest tests/test_data_live_smoke.py -v`
Expected: PASS or SKIPPED (SKIPPED is fine pre-token)

- [ ] **Step 3: Run the FULL suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: all prior 78 tests + new data-layer tests PASS (smoke may skip)

---

## Task 9: Phase commit + real run (after user sign-off)

> Per the commit policy, this is the FIRST commit. Do it only after Task 8 is green AND the user signs off.

- [ ] **Step 1: Confirm full suite green**

Run: `python -m pytest -q`
Expected: all PASS

- [ ] **Step 2: Stage + commit the phase**

```bash
git add execution/data/ tests/test_data_*.py directives/fetch_bulk_data.md \
        execution/params.yaml requirements.txt .gitignore \
        docs/superpowers/specs/2026-06-04-questrade-bulk-data-provider-design.md \
        docs/superpowers/plans/2026-06-04-questrade-bulk-data-provider.md
git commit -m "Phase 5 (data): Questrade bulk data provider with pagination + yfinance backup"
```

- [ ] **Step 3: Real backfill (requires the user's token in `.env`)**

Run: `pip install -r requirements.txt && python -m execution.data.backfill`
Expected: `data/bars/` fills with `{SYMBOL}_{tf}.json` + `manifest.json`; summary mostly `ok`.
Verify: `python -c "from execution.backtest.store import BarStore; s=BarStore('data/bars'); print(len(s.bars('SPY','5m')), 'SPY 5m bars')"`
Expected: thousands of bars (vs ~500 before).

- [ ] **Step 4: Re-run the research question**

Run (PowerShell): `$env:PYTHONPATH="."; python -c "from execution.config import load_params; from execution.backtest.store import BarStore; from execution.backtest.runner import gate_lift; p=load_params(); u=p['data']['universe']; print(gate_lift(u, BarStore('data/bars'), params=p))"`
Expected: a `{'gate_on': {...}, 'gate_off': {...}}` summary computed over real bulk history — finally answering whether the 1h-trend gate helps or hurts.

- [ ] **Step 5: Record the finding** in `.claude/.../memory/backtest-data-limited.md` (update: now data-rich; capture the gate verdict).

---

## Self-Review

**Spec coverage:** problem/goal (Task 9 payoff) · port client (T5) · pagination+guard (T1-3,7a) · normalize (T4) · yfinance 1h/1d-only+clamp (T6) · per-series fallback, 5m hard-fail, gaps (7a,7c) · manifest provenance (7b) · output format/dir (7b) · resumability (7c) · params block (T0) · deps+gitignore (T0) · directive (8a) · tests incl. live smoke (8b) — all covered.

**Placeholder scan:** every code/test step contains complete code; no TBD/TODO.

**Type consistency:** `fetch_series_questrade -> (rows, gaps)` used consistently; `SeriesUnavailable`/`QuestradeAPIError` imported from one place; `write_series(..., source, gaps, status)` signature matches all call sites; manifest key `f"{symbol}_{tf}"` uniform; `_yf_fetch` indirection matches the monkeypatch in 7c.
