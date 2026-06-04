# Backtest Harness (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lookahead-safe backtest engine that replays cached OHLCV bars, generates sweep signals (reusing the Phase 1 detection core), applies the probability filters, simulates trade outcomes, and reports trade stats sliced by time-of-day / level type — plus a trend-gate ON-vs-OFF lift comparison.

**Architecture:** A pure-logic `execution/backtest/` subpackage. A `BarStore` abstracts data access (reads cached JSON bar files now; a bulk vendor drops in later behind the same interface). The runner wires Phase 1 (`levels`/`detect`/`filters`/`trend`/`signals`) to backtest-only helpers (multi-sweep replay, modeled spread, RS from aligned benchmark closes, trade simulation, stats). Everything is deterministic and unit-tested with synthetic bars; real-data seeding is an operational step after the suite is green.

**Tech Stack:** Python 3.11+, `pytest`, `pyyaml`. Reuses the Phase 1 `execution/` modules unchanged.

---

## ⚠️ Commit policy (unchanged)
Per user preference, **no `git init` / `git commit` during these tasks.** Each task's checkpoint is a green test run. We commit once, after the suite is green and the user signs off.

## Data & fidelity decisions (locked)
- **Source:** cached bar files via `BarStore` (pluggable). Seed = multi-symbol × ~7 sessions from the tv-mcp feed (500-bar cap). This validates the machine + gives a directional read; it is **not** statistically significant — a bulk source scales it later with no engine change.
- **RS:** real, computed from an aligned benchmark series (SPY/QQQ 5m).
- **Spread/liquidity:** ADV from daily bars (real); **spread is MODELED** (`modeled_spread(price, adv)`) since historical L1 quotes aren't available; book-size check skipped.
- **Path resolution:** when one 5m bar straddles both stop and target, resolve **stop-first (conservative)**. (1m refinement is deferred — the 1m feed only reaches ~1.3 days, so it isn't worth wiring for v1.)
- **ATR threshold:** `atr5` is fixed per session from the `atr_len` 5m bars **before** the session open (lookahead-safe), used for both `pen_min` and the R:R buffer that day.

## File structure
| File | Responsibility |
|---|---|
| `execution/backtest/__init__.py` | package marker (empty) |
| `execution/backtest/store.py` | `BarStore` — load cached `{SYMBOL}_{tf}.json`; list sessions |
| `execution/backtest/replay.py` | `find_all_sweeps` — every-sweep replay over a session |
| `execution/backtest/features.py` | `adv_from_daily`, `modeled_spread`, `rvol_from_adv`, `killzone`, `close_now_prev` |
| `execution/backtest/simulate.py` | `Trade` + `simulate_trade` (stop/target, straddle→stop-first, timeout) |
| `execution/backtest/stats.py` | `summarize`, `slice_by` |
| `execution/backtest/runner.py` | `run_backtest`, `gate_lift` (wires Phase 1 + helpers) |
| `directives/run_backtest.md` | SOP (created in final task, not TDD) |
| `tests/test_bt_*.py` | one test module per source module |

**Units:** returns/spreads are fractions (carried over from Phase 1). `BARS_PER_RTH = 78` (6.5h × 12). Timestamps are UTC; ET display uses fixed −4h (EDT, valid for the June seed data).

---

### Task 1: Backtest package scaffolding

**Files:**
- Create: `execution/backtest/__init__.py` (empty)

- [ ] **Step 1: Create the package marker**

Create empty file `execution/backtest/__init__.py`.

- [ ] **Step 2: Verify the package imports**

Run: `python -c "import execution.backtest; print('ok')"`
Expected: prints `ok` (run from project root; `pyproject.toml` already sets `pythonpath`).

---

### Task 2: BarStore

**Files:**
- Create: `execution/backtest/store.py`
- Test: `tests/test_bt_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_store.py
import json
from datetime import date
from execution.models import Bar
from execution.backtest.store import BarStore

def _write(tmp_path, name, rows):
    (tmp_path / name).write_text(json.dumps(rows))

def test_loads_bars_and_lists_sessions(tmp_path):
    _write(tmp_path, "ABC_5m.json", [
        {"ts": "2026-06-03T19:55:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        {"ts": "2026-06-04T13:30:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        {"ts": "2026-06-04T13:35:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ])
    store = BarStore(tmp_path)
    bars = store.bars("ABC", "5m")
    assert len(bars) == 3 and isinstance(bars[0], Bar)
    assert store.sessions("ABC") == [date(2026, 6, 3), date(2026, 6, 4)]

def test_missing_file_returns_empty(tmp_path):
    assert BarStore(tmp_path).bars("NOPE", "1h") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/store.py
from __future__ import annotations
import json
from pathlib import Path
from datetime import date
from execution.models import Bar


class BarStore:
    """Loads cached OHLCV bar files named '{SYMBOL}_{tf}.json' from a directory.

    This is the single swap point for data sources: a bulk vendor only needs to
    produce the same files (or subclass and override `bars`).
    """

    def __init__(self, root):
        self.root = Path(root)
        self._cache: dict[tuple[str, str], list[Bar]] = {}

    def bars(self, symbol: str, tf: str) -> list[Bar]:
        key = (symbol, tf)
        if key not in self._cache:
            path = self.root / f"{symbol}_{tf}.json"
            if not path.exists():
                self._cache[key] = []
            else:
                rows = json.loads(path.read_text())
                self._cache[key] = [Bar.from_questrade(r) for r in rows]
        return self._cache[key]

    def sessions(self, symbol: str) -> list[date]:
        seen = sorted({b.ts.date() for b in self.bars(symbol, "5m")})
        return seen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_store.py -q`
Expected: PASS (2 passed)

---

### Task 3: Every-sweep replay

**Files:**
- Create: `execution/backtest/replay.py`
- Test: `tests/test_bt_replay.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_replay.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.detect import detect_bullish_sweep
from execution.backtest.replay import find_all_sweeps

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

def test_finds_multiple_sweeps_of_same_level():
    level = 100.0
    bars = [_bar(0, 100.3, 100.35, 99.80, 100.20),   # sweep #1 (same-bar reclaim)
            _bar(1, 100.2, 100.30, 100.10, 100.25),  # away from level
            _bar(2, 100.2, 100.30, 99.78, 100.21)]   # sweep #2 (same-bar reclaim)
    out = find_all_sweeps(bars, level, detect_bullish_sweep, pen_min=0.05, max_reentry_bars=1)
    assert len(out) == 2
    assert out[0].reentry_index == 0 and out[1].reentry_index == 2
    assert out[0].sweep_ts < out[1].sweep_ts

def test_returns_empty_when_no_sweep():
    bars = [_bar(0, 101, 101.2, 100.9, 101.1)]
    assert find_all_sweeps(bars, 100.0, detect_bullish_sweep, pen_min=0.05, max_reentry_bars=1) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_replay.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.replay'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/replay.py
from __future__ import annotations
from dataclasses import replace
from execution.detect import SweepCandidate


def find_all_sweeps(bars, level_price, detect_fn, *, pen_min, max_reentry_bars,
                    **kw) -> list[SweepCandidate]:
    """Repeatedly scan a session, collecting every sweep (every-sweep re-arm).

    After each hit, advance past its re-entry bar. Indices on returned candidates
    are rebuilt to be absolute (relative to `bars`); timestamps are already absolute.
    """
    out: list[SweepCandidate] = []
    start = 0
    while start < len(bars):
        c = detect_fn(bars[start:], level_price, pen_min=pen_min,
                      max_reentry_bars=max_reentry_bars, **kw)
        if c is None:
            break
        out.append(replace(c, sweep_index=start + c.sweep_index,
                           reentry_index=start + c.reentry_index))
        start = start + c.reentry_index + 1
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_replay.py -q`
Expected: PASS (2 passed)

---

### Task 4: Backtest feature helpers

**Files:**
- Create: `execution/backtest/features.py`
- Test: `tests/test_bt_features.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_features.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.backtest.features import (
    adv_from_daily, modeled_spread, rvol_from_adv, killzone, close_now_prev)

def _b(ts, c, v=100):
    return Bar(ts=ts, o=c, h=c, l=c, c=c, v=v)

def test_adv_from_daily_averages_recent_volume():
    days = [_b(datetime(2026, 6, d), 100, v=vol) for d, vol in [(1, 10), (2, 20), (3, 30)]]
    assert adv_from_daily(days, lookback=2) == 25.0   # mean of last two

def test_modeled_spread_steps_with_liquidity():
    assert modeled_spread(100.0, 6_000_000) == 0.01    # 1 bp -> 0.01, floored
    assert modeled_spread(500.0, 2_000_000) == round(500 * 3 / 10_000, 2)   # 3 bps
    assert modeled_spread(50.0, 500_000) == round(50 * 8 / 10_000, 2)       # 8 bps

def test_rvol_from_adv_uses_per_bar_average():
    # adv 78000 -> avg 5m vol 1000 ; a 1500-vol bar -> rvol 1.5
    assert rvol_from_adv(1500, 78_000) == 1.5
    assert rvol_from_adv(1500, 0) == 0.0

def test_killzone_buckets_by_eastern_time():
    open_utc = datetime(2026, 6, 4, 13, 35)   # 09:35 ET
    power_utc = datetime(2026, 6, 4, 18, 30)  # 14:30 ET
    mid_utc = datetime(2026, 6, 4, 16, 30)    # 12:30 ET
    assert killzone(open_utc) == "ny_open"
    assert killzone(power_utc) == "power_hour"
    assert killzone(mid_utc) == "midday"

def test_close_now_prev_returns_now_and_lagged_close():
    base = datetime(2026, 6, 4, 14, 0)
    bars = [_b(base + timedelta(minutes=5 * i), 100 + i) for i in range(6)]
    now_prev = close_now_prev(bars, base + timedelta(minutes=25), 20)  # now idx5; 20min back -> idx1
    assert now_prev == (105.0, 101.0)
    assert close_now_prev(bars, base, 20) is None   # no bar 20 min before base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_features.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.features'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/features.py
from __future__ import annotations
from datetime import time, timedelta
from execution.models import Bar

BARS_PER_RTH = 78   # 6.5h * 12 five-minute bars


def adv_from_daily(daily_bars: list[Bar], lookback: int = 20) -> float:
    vols = [b.v for b in daily_bars[-lookback:]]
    return sum(vols) / len(vols) if vols else 0.0


def modeled_spread(price: float, adv_shares: float) -> float:
    """Placeholder spread model (no historical L1 quotes): tighter for more liquid names."""
    bps = 1.0 if adv_shares >= 5_000_000 else 3.0 if adv_shares >= 1_000_000 else 8.0
    return max(0.01, round(price * bps / 10_000, 2))


def rvol_from_adv(bar_volume: float, adv_shares: float) -> float:
    avg_5m = adv_shares / BARS_PER_RTH
    return bar_volume / avg_5m if avg_5m > 0 else 0.0


def killzone(ts) -> str:
    t = (ts - timedelta(hours=4)).time()   # UTC -> US/Eastern (EDT)
    if time(9, 30) <= t < time(11, 30):
        return "ny_open"
    if time(14, 0) <= t < time(15, 30):
        return "power_hour"
    return "midday"


def close_now_prev(bars: list[Bar], ts, window_minutes: int):
    """(close at-or-before ts, close at-or-before ts - window_minutes), or None.

    Both legs are anchored by TIMESTAMP (not array index), so a symbol and its
    benchmark align by wall-clock even when one series has a gap/halt the other lacks.
    """
    prev_ts = ts - timedelta(minutes=window_minutes)
    now_c = prev_c = None
    for b in bars:
        if b.ts <= ts:
            now_c = b.c
        if b.ts <= prev_ts:
            prev_c = b.c
    return (now_c, prev_c) if now_c is not None and prev_c is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_features.py -q`
Expected: PASS (5 passed)

---

### Task 5: Trade simulation

**Files:**
- Create: `execution/backtest/simulate.py`
- Test: `tests/test_bt_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_simulate.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.backtest.simulate import simulate_trade

def _bar(i, o, h, l, c):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=100)

BASE = dict(direction="long", level_type="PDL", symbol="ABC",
            entry_time=datetime(2026, 6, 4, 13, 0), entry_price=100.0,
            stop=99.0, target=102.0, killzone="ny_open", rs_score=0.4)

def test_target_hit_returns_positive_r():
    fwd = [_bar(0, 100.1, 100.5, 100.0, 100.4), _bar(1, 100.4, 102.1, 100.3, 101.9)]
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "target" and t.bars_held == 2
    assert round(t.r_multiple, 2) == 2.0    # reward 2.0 / risk 1.0

def test_stop_hit_returns_minus_one_r():
    fwd = [_bar(0, 100.0, 100.2, 98.9, 99.5)]
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "stop" and round(t.r_multiple, 2) == -1.0

def test_straddle_resolves_stop_first():
    fwd = [_bar(0, 100.0, 102.5, 98.5, 101.0)]   # bar hits BOTH stop and target
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "stop" and round(t.r_multiple, 2) == -1.0

def test_timeout_marks_partial_r_at_last_close():
    fwd = [_bar(0, 100.0, 100.6, 99.8, 100.5)]   # neither hit
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "timeout" and round(t.r_multiple, 2) == 0.5   # +0.5/1.0

def test_short_target_hit():
    short = {**BASE, "direction": "short", "stop": 101.0, "target": 98.0}
    fwd = [_bar(0, 100.0, 100.2, 97.9, 98.1)]
    t = simulate_trade(forward_bars=fwd, **short)
    assert t.exit_reason == "target" and round(t.r_multiple, 2) == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_simulate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.simulate'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/simulate.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from execution.models import Bar


@dataclass
class Trade:
    symbol: str
    direction: str
    level_type: str
    entry_time: datetime
    entry_price: float
    stop: float
    target: float
    exit_time: datetime
    exit_price: float
    exit_reason: str        # "target" | "stop" | "timeout"
    r_multiple: float
    bars_held: int
    killzone: str
    rs_score: float


def _r(direction: str, entry: float, exit_price: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    return (exit_price - entry) / risk if direction == "long" else (entry - exit_price) / risk


def simulate_trade(*, direction: str, level_type: str, symbol: str, entry_time: datetime,
                   entry_price: float, stop: float, target: float, forward_bars: list[Bar],
                   killzone: str = "", rs_score: float = 0.0) -> Trade:
    """Walk forward bars; exit at first of stop/target. A bar that straddles both
    resolves stop-first (conservative). No hit by the end -> timeout at last close.
    """
    risk = abs(entry_price - stop)

    def make(exit_time, exit_price, reason, held):
        return Trade(symbol=symbol, direction=direction, level_type=level_type,
                     entry_time=entry_time, entry_price=entry_price, stop=stop, target=target,
                     exit_time=exit_time, exit_price=exit_price, exit_reason=reason,
                     r_multiple=_r(direction, entry_price, exit_price, risk),
                     bars_held=held, killzone=killzone, rs_score=rs_score)

    if not forward_bars:
        return make(entry_time, entry_price, "timeout", 0)

    for k, bar in enumerate(forward_bars, start=1):
        if direction == "long":
            hit_stop, hit_tgt = bar.l <= stop, bar.h >= target
        else:
            hit_stop, hit_tgt = bar.h >= stop, bar.l <= target
        if hit_stop:                       # stop-first on straddle
            return make(bar.ts, stop, "stop", k)
        if hit_tgt:
            return make(bar.ts, target, "target", k)

    last = forward_bars[-1]
    return make(last.ts, last.c, "timeout", len(forward_bars))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_simulate.py -q`
Expected: PASS (5 passed)

---

### Task 6: Stats aggregation

**Files:**
- Create: `execution/backtest/stats.py`
- Test: `tests/test_bt_stats.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_stats.py
from execution.backtest.stats import summarize, slice_by

class T:   # lightweight trade stand-in (summarize only reads r_multiple/bars_held/killzone)
    def __init__(self, r, held=1, kz="ny_open"):
        self.r_multiple, self.bars_held, self.killzone = r, held, kz

def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0 and s["win_rate"] == 0.0 and s["expectancy_r"] == 0.0

def test_summarize_basic_metrics():
    trades = [T(2.0), T(2.0), T(-1.0), T(-1.0)]   # 2 wins +2R, 2 losses -1R
    s = summarize(trades)
    assert s["n"] == 4 and s["win_rate"] == 0.5
    assert round(s["expectancy_r"], 2) == 0.5            # (2+2-1-1)/4
    assert round(s["profit_factor"], 2) == 2.0           # 4 / 2

def test_profit_factor_infinite_when_no_losses():
    assert summarize([T(2.0), T(1.0)])["profit_factor"] == float("inf")

def test_slice_by_groups_and_summarizes():
    trades = [T(2.0, kz="ny_open"), T(-1.0, kz="ny_open"), T(2.0, kz="midday")]
    by = slice_by(trades, lambda t: t.killzone)
    assert by["ny_open"]["n"] == 2 and by["midday"]["n"] == 1
    assert by["midday"]["win_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.stats'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/stats.py
from __future__ import annotations


def summarize(trades) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0,
                "profit_factor": 0.0, "avg_bars_held": 0.0}
    wins = [t.r_multiple for t in trades if t.r_multiple > 0]
    losses = [t.r_multiple for t in trades if t.r_multiple <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "expectancy_r": sum(t.r_multiple for t in trades) / n,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_bars_held": sum(t.bars_held for t in trades) / n,
    }


def slice_by(trades, keyfn) -> dict:
    groups: dict = {}
    for t in trades:
        groups.setdefault(keyfn(t), []).append(t)
    return {k: summarize(v) for k, v in groups.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_stats.py -q`
Expected: PASS (4 passed)

---

### Task 7: Runner + gate-lift

**Files:**
- Create: `execution/backtest/runner.py`
- Test: `tests/test_bt_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_runner.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.backtest.runner import run_backtest, gate_lift

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

class StubStore:
    """In-memory store so the runner test needs no files."""
    def __init__(self, data, sessions):
        self._data, self._sessions = data, sessions
    def bars(self, symbol, tf):
        return self._data.get((symbol, tf), [])
    def sessions(self, symbol):
        return self._sessions

def _make_store():
    from datetime import date
    d = date(2026, 6, 4)
    s = datetime(2026, 6, 4, 13, 30)   # 09:30 ET (ny_open killzone)
    # prior day (06-03) daily bar -> PDL=99.0, PDH=110.0
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000),
             _b(datetime(2026, 6, 4), 100, 111, 98, 110, v=80_000_000)]
    # 20 warmup 5m bars (prior session) ~99.3 with small range -> ATR context
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    # session: build above PDL, then dip-sweep PDL with same-bar reclaim (high vol), run to PDH
    sess = [
        _b(s,                          99.20, 99.40, 99.10, 99.30),
        _b(s + timedelta(minutes=5),   99.30, 99.50, 99.20, 99.40),
        _b(s + timedelta(minutes=10),  99.40, 99.60, 99.30, 99.50),
        _b(s + timedelta(minutes=15),  99.50, 99.70, 99.40, 99.60),
        _b(s + timedelta(minutes=20),  99.60, 99.80, 98.50, 99.70, v=2_000_000),  # sweep+reclaim
        _b(s + timedelta(minutes=25),  99.70, 100.50, 99.60, 100.40),
        _b(s + timedelta(minutes=30),  100.40, 103.00, 100.30, 102.50),
        _b(s + timedelta(minutes=35),  102.50, 110.50, 102.40, 110.20),   # hits PDH 110 target
    ]
    sym5 = warm + sess
    # benchmark (SPY) flat -> the symbol (up 0.4% over the 20-min window) shows relative strength
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in sym5]
    # 1h closes steadily rising -> last completed 1h above its EMA -> trend 'up' (long allowed)
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    data = {("ABC", "5m"): sym5, ("ABC", "1d"): daily, ("ABC", "1h"): h1,
            ("SPY", "5m"): bench5}
    return StubStore(data, [d])

def test_run_backtest_produces_a_winning_trade():
    store = _make_store()
    res = run_backtest(["ABC"], store, benchmark="SPY", trend_gate=True)
    assert res["overall"]["n"] >= 1
    # the crafted long sweep should reach the PDH target
    assert any(t.exit_reason == "target" for t in res["trades"])
    assert "by_killzone" in res and "by_level" in res

def test_gate_lift_returns_on_off_comparison():
    store = _make_store()
    lift = gate_lift(["ABC"], store, benchmark="SPY")
    assert "gate_on" in lift and "gate_off" in lift
    assert lift["gate_off"]["n"] >= lift["gate_on"]["n"]   # OFF never filters fewer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.backtest.runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/backtest/runner.py
from __future__ import annotations
from datetime import timedelta

from execution.levels import previous_session_levels
from execution.indicators import atr
from execution.detect import penetration_min, detect_bullish_sweep, detect_bearish_sweep
from execution.filters import relative_strength, liquidity_ok, risk_reward, RSResult
from execution.trend import htf_trend
from execution.signals import build_signal
from execution.config import load_params
from execution.backtest.replay import find_all_sweeps
from execution.backtest.features import (
    adv_from_daily, modeled_spread, rvol_from_adv, killzone, close_now_prev)
from execution.backtest.simulate import simulate_trade
from execution.backtest.stats import summarize, slice_by


def run_backtest(symbols, store, *, params=None, benchmark="SPY", trend_gate=True) -> dict:
    p = params or load_params()
    d, rs, liq, rr, tr = p["detection"], p["rs"], p["liquidity"], p["rr"], p["trend"]
    trades = []

    for sym in symbols:
        daily = store.bars(sym, "1d")
        bars5 = store.bars(sym, "5m")
        h1 = store.bars(sym, "1h")
        bench5 = store.bars(benchmark, "5m")
        adv = adv_from_daily(daily)
        if not daily or not bars5:
            continue

        for session in store.sessions(sym):
            try:
                lvl = previous_session_levels(daily, session)
            except ValueError:
                continue
            pre = [b for b in bars5 if b.ts.date() < session]
            if len(pre) < d["atr_len"] + 1:
                continue
            atr5 = atr(pre, d["atr_len"])
            pen = penetration_min(atr5, d["pen_atr_frac"], d["min_pen_abs"])
            sess = [b for b in bars5 if b.ts.date() == session]

            sides = [("long", detect_bullish_sweep, lvl.pdl, lvl.pdh),
                     ("short", detect_bearish_sweep, lvl.pdh, lvl.pdl)]
            for direction, fn, level, target in sides:
                for c in find_all_sweeps(sess, level, fn, pen_min=pen,
                                         max_reentry_bars=d["max_reentry_bars"]):
                    spread = modeled_spread(c.reentry_close, adv)
                    rr_res = risk_reward(direction=direction, entry=c.reentry_close,
                                         wick_extreme=c.wick_extreme, target=target, atr5=atr5,
                                         current_spread=spread, buf_abs=rr["buf_abs"],
                                         buf_atr_frac=rr["buf_atr_frac"], min_rr=rr["min_rr"])
                    sp = close_now_prev(bars5, c.reentry_ts, rs["rs_window_min"])   # continuous, ts-anchored
                    bp = close_now_prev(bench5, c.reentry_ts, rs["rs_window_min"])
                    if sp and bp:
                        rs_res = relative_strength(sym_now=sp[0], sym_prev=sp[1],
                                                   bench_now=bp[0], bench_prev=bp[1],
                                                   rs_thresh=rs["rs_thresh"],
                                                   bench_flat_max=rs["bench_flat_max"])
                    else:
                        rs_res = RSResult(0.0, 0.0, 0.0, False, False)
                    reentry_bar = sess[c.reentry_index]
                    rvol = rvol_from_adv(reentry_bar.v, adv)
                    mid = c.reentry_close
                    liq_res = liquidity_ok(
                        adv_20d=adv, bar_volume=reentry_bar.v, bar_close=c.reentry_close,
                        rvol=rvol, bid=mid - spread / 2, ask=mid + spread / 2,
                        bid_size=1e9, ask_size=1e9, risk=rr_res.risk,
                        min_adv_shares=liq["min_adv_shares"],
                        min_bar_dollar_vol=liq["min_bar_dollar_vol"], min_rvol=liq["min_rvol"],
                        max_spread_abs=liq["max_spread_abs"], max_spread_pct=liq["max_spread_pct"],
                        min_book_shares=None, spread_risk_frac=liq["spread_risk_frac"])
                    if trend_gate:
                        closed = [b.c for b in h1 if b.ts + timedelta(hours=1) <= c.reentry_ts]
                        trend = htf_trend(closed, ema_len=tr["htf_ema_len"],
                                          require_slope=tr["htf_require_slope"])
                    else:
                        trend = None
                    sig = build_signal(candidate=c, symbol=sym, rs=rs_res, liquidity=liq_res,
                                       rr=rr_res, benchmark=benchmark,
                                       rs_window_min=rs["rs_window_min"], spread_abs=spread,
                                       spread_bps=spread / mid * 10_000 if mid else 0.0,
                                       volume_context={"rvol": rvol, "adv": adv},
                                       alt_targets={}, killzone=killzone(c.reentry_ts),
                                       mode="backtest", htf_trend=trend)
                    if not sig.qualified:
                        continue
                    forward = [b for b in sess if b.ts > c.reentry_ts]
                    trades.append(simulate_trade(
                        direction=direction, level_type=c.level_type, symbol=sym,
                        entry_time=c.reentry_ts, entry_price=rr_res.entry, stop=rr_res.stop,
                        target=rr_res.target, forward_bars=forward,
                        killzone=sig.killzone, rs_score=rs_res.rs))

    return {
        "trades": trades,
        "overall": summarize(trades),
        "by_killzone": slice_by(trades, lambda t: t.killzone),
        "by_level": slice_by(trades, lambda t: t.level_type),
    }


def gate_lift(symbols, store, *, params=None, benchmark="SPY") -> dict:
    on = run_backtest(symbols, store, params=params, benchmark=benchmark, trend_gate=True)
    off = run_backtest(symbols, store, params=params, benchmark=benchmark, trend_gate=False)
    return {"gate_on": on["overall"], "gate_off": off["overall"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_runner.py -q`
Expected: PASS (2 passed)

---

### Task 8: Backtest params + config

**Files:**
- Modify: `execution/params.yaml` (append a `backtest` group)
- Test: `tests/test_bt_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bt_config.py
from execution.config import load_params

def test_backtest_group_present():
    p = load_params()
    assert p["backtest"]["benchmark"] == "SPY"
    assert p["backtest"]["bars_per_rt_day"] == 78
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bt_config.py -q`
Expected: FAIL with `KeyError: 'backtest'`

- [ ] **Step 3: Append to `execution/params.yaml`**

Add this block at the end of the file:

```yaml
backtest:
  benchmark: "SPY"        # default RS benchmark
  bars_per_rt_day: 78     # 6.5h * 12 five-minute bars (for rvol model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bt_config.py -q`
Expected: PASS (1 passed)

---

### Task 9: Directive + full-suite checkpoint

**Files:**
- Create: `directives/run_backtest.md`
- Test: none (verification)

- [ ] **Step 1: Create the directive SOP**

Create `directives/run_backtest.md`:

```markdown
# Directive: Run the Backtest

**Goal:** Measure sweep-strategy performance on cached bars, including the 1h-trend-gate lift.

**Inputs:** cached `{SYMBOL}_{tf}.json` files (5m, 1h, 1d) under a data dir, plus the benchmark (SPY) 5m, produced by the data-seeding step.

**Tools:** `execution/backtest/runner.py` — `run_backtest(symbols, store, ...)` and `gate_lift(symbols, store, ...)`.

**Steps:**
1. Seed data: fetch multi-symbol x recent sessions via the tv-mcp `get_ohlcv` (500-bar cap) and write each series to `{SYMBOL}_{tf}.json`.
2. `store = BarStore(data_dir)`.
3. `run_backtest(symbols, store)` -> overall + by_killzone + by_level stats.
4. `gate_lift(symbols, store)` -> compare expectancy with the 1h-trend gate ON vs OFF.

**Edge cases / limits:**
- 500-bar feed cap -> ~7 sessions of 5m. Results are directional, not significant. Swap in a bulk source (more files) to scale.
- Spread is MODELED (no historical L1). ADV from daily bars. Straddle bars resolve stop-first.
```

- [ ] **Step 2: Run the entire suite**

Run: `pytest -q`
Expected: PASS — **all Phase 1 (39) + Phase 2 (21) = 60 passed**, 0 failed.
(Phase 2 adds: store 2, replay 2, features 5, simulate 5, stats 4, runner 2, config 1.)

- [ ] **Step 3: Report to user (no commit)**

Summarize modules + green count; note that real-data seeding + reading the gate-lift result is the next operational step, and that we still await git sign-off.

---

## Self-Review

**1. Spec coverage** (vs the backtest section of `docs/superpowers/specs/2026-06-04-liquidity-sweep-scanner-design.md`):
- Generate raw sweeps (every-sweep replay) → Task 3 ✅
- Apply 3 filters (RS real, liquidity w/ modeled spread, R:R) → Task 7 ✅
- Lookahead safety (levels D−1, atr5 from pre-session bars, 1h trend from completed bars, signals on 5m close) → Tasks 3/7 ✅
- Trade sim w/ stop-first straddle + timeout → Task 5 ✅
- Stats (win rate, expectancy R, profit factor, avg duration) → Task 6 ✅
- Slices (time-of-day killzone, level type) + gate ON/OFF lift → Tasks 6/7 ✅
- Pluggable data source → Task 2 ✅
- *Deferred intentionally:* RS-decile & liquidity-bucket slices (small N — RS sign/killzone first), 1m path refinement (1m feed too shallow), bulk vendor loader. Noted, not accidental.

**2. Placeholder scan:** No TBD/TODO; every code step is complete; `modeled_spread` is a deliberate, documented placeholder (not a gap).

**3. Type consistency:** Reuses Phase 1 symbols unchanged (`Bar`, `RSResult`, `risk_reward`/`RRResult`, `liquidity_ok`, `htf_trend`, `build_signal` with `htf_trend=`/`mode=`). New `Trade` defined once (Task 5) and read by `stats` (Task 6) and produced by `runner` (Task 7) with matching fields (`r_multiple`, `bars_held`, `killzone`, `level_type`). `find_all_sweeps` returns `SweepCandidate` with absolute indices; runner uses `sess[c.reentry_index]` consistently.

---

## Next (after this engine is green)
- **Seed + run:** fetch a small multi-symbol universe via the feed, run `gate_lift`, and read whether the 1h-trend gate helps or hurts (the question the SPY smoke test raised).
- **Then:** Phase 3 (live scanner + state machine), Phase 4 (dashboard).
