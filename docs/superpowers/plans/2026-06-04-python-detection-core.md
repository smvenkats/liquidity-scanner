# Python Detection Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-logic, fully unit-tested detection core for the liquidity-sweep scanner — lookahead-safe levels, sweep detection, the three probability filters, and signal assembly — with no live broker dependency.

**Architecture:** A small `execution/` Python package of focused, side-effect-free modules. Every function takes explicit scalar/dataclass inputs (no global config object) so each is deterministically testable with synthetic bars. A later phase wires these to Questrade data and the dashboard; this phase is the trustworthy heart.

**Tech Stack:** Python 3.11+, `pytest`, `pyyaml`. Standard library `dataclasses`/`datetime` for models.

---

## ⚠️ Commit policy for this plan

Per user preference (no git until locally tested and both parties satisfied), **do not run `git init` or any `git commit` during these tasks.** Each task ends with a **green test run** as its checkpoint instead of a commit. After the full suite passes and the user signs off, we git-init and make the first commit in one step.

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | pytest config (`pythonpath = ["."]`) |
| `requirements.txt` | `pytest`, `pyyaml` |
| `execution/__init__.py` | marks package (empty) |
| `execution/models.py` | pure data: `Bar`, `Quote`, `Level` |
| `execution/levels.py` | lookahead-safe PDH/PDL from daily bars |
| `execution/indicators.py` | `atr`, `rvol`, `session_vwap` |
| `execution/detect.py` | `penetration_min`, `SweepCandidate`, bullish/bearish sweep scan |
| `execution/filters.py` | `relative_strength`, `liquidity_ok`, `risk_reward` |
| `execution/trend.py` | `ema`, `htf_trend` (1h bias from completed 1h closes) |
| `execution/signals.py` | `Signal`, `make_signal_id`, `build_signal` (qualify, incl. 1h trend gate) |
| `execution/config.py` + `execution/params.yaml` | default tunables loader |
| `tests/test_*.py` | one test module per source module |

**Units convention (consistency-critical):** returns/spreads are **fractions** in code (0.30% → `0.003`, 8 bps → `0.0008`). Price buffers (`min_pen_abs`, `buf_abs`) are **absolute USD**. The spec's `min_pen_ticks`/`buf_ticks` map to `min_pen_abs`/`buf_abs` (USD floors).

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `execution/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Create `requirements.txt`**

```
pytest>=8.0
pyyaml>=6.0
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 3: Create empty package markers**

Create `execution/__init__.py` and `tests/__init__.py` as empty files.

- [ ] **Step 4: Install deps and verify pytest runs**

Run: `pip install -r requirements.txt && pytest -q`
Expected: `no tests ran` (exit code 5) — confirms pytest is wired and `pythonpath` is set.

---

### Task 2: Data models

**Files:**
- Create: `execution/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import datetime
from execution.models import Bar, Quote, Level

def test_bar_from_questrade_parses_iso_ts_and_floats():
    d = {"ts": "2026-06-04T16:20:00+00:00", "o": 756.38, "h": 756.67,
         "l": 756.30, "c": 756.61, "v": 526232}
    b = Bar.from_questrade(d)
    assert isinstance(b.ts, datetime)
    assert b.ts.hour == 16 and b.h == 756.67 and b.v == 526232.0

def test_quote_spread_and_mid():
    q = Quote(bid=10.00, ask=10.04, bid_size=1500, ask_size=1200)
    assert round(q.spread, 4) == 0.04
    assert q.mid == 10.02
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float

    @classmethod
    def from_questrade(cls, d: dict) -> "Bar":
        return cls(
            ts=datetime.fromisoformat(d["ts"]),
            o=float(d["o"]), h=float(d["h"]), l=float(d["l"]),
            c=float(d["c"]), v=float(d["v"]),
        )


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2


@dataclass(frozen=True)
class Level:
    pdh: float
    pdl: float
    source_date: date
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -q`
Expected: PASS (2 passed)

---

### Task 3: Lookahead-safe levels

**Files:**
- Create: `execution/levels.py`
- Test: `tests/test_levels.py`

- [ ] **Step 1: Write the failing test (includes the lookahead audit)**

```python
# tests/test_levels.py
from datetime import datetime, date
import pytest
from execution.models import Bar
from execution.levels import previous_session_levels

def _daily(d, h, l):
    return Bar(ts=datetime.fromisoformat(d + "T00:00:00+00:00"),
               o=h, h=h, l=l, c=l, v=1)

def test_uses_prior_completed_day_only():
    bars = [_daily("2026-06-01", 100, 90),
            _daily("2026-06-02", 110, 95),
            _daily("2026-06-03", 999, 1)]   # the forming session — MUST be ignored
    lvl = previous_session_levels(bars, date(2026, 6, 3))
    assert lvl.pdh == 110 and lvl.pdl == 95
    assert lvl.source_date == date(2026, 6, 2)

def test_raises_when_no_prior_day():
    bars = [_daily("2026-06-03", 100, 90)]
    with pytest.raises(ValueError):
        previous_session_levels(bars, date(2026, 6, 3))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_levels.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.levels'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/levels.py
from __future__ import annotations
from datetime import date
from execution.models import Bar, Level


def previous_session_levels(daily_bars: list[Bar], session_date: date) -> Level:
    """PDH/PDL from the most recent COMPLETED day strictly before session_date.

    The forming session's own bar can never contribute to its level — this is the
    lookahead-bias lockdown on the Python side.
    """
    prior = [b for b in daily_bars if b.ts.date() < session_date]
    if not prior:
        raise ValueError(f"no daily bar before {session_date}")
    b = max(prior, key=lambda x: x.ts)
    return Level(pdh=b.h, pdl=b.l, source_date=b.ts.date())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_levels.py -q`
Expected: PASS (2 passed)

---

### Task 4: Indicators

**Files:**
- Create: `execution/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_indicators.py
from datetime import datetime, timedelta
import pytest
from execution.models import Bar
from execution.indicators import atr, rvol, session_vwap

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

def test_atr_simple_mean_of_true_range():
    # 3 bars, length=2. prev close chains: TR2=max(12-8,|12-10|,|8-10|)=4 ; TR3=max(11-9,|11-9|,|9-9|)=2
    bars = [_bar(0, 10, 10, 10, 10), _bar(1, 10, 12, 8, 9), _bar(2, 9, 11, 9, 9)]
    assert atr(bars, 2) == 3.0

def test_atr_needs_length_plus_one_bars():
    bars = [_bar(0, 10, 10, 10, 10), _bar(1, 10, 12, 8, 9)]
    with pytest.raises(ValueError):
        atr(bars, 2)

def test_rvol_ratio_and_zero_guard():
    assert rvol(150, 100) == 1.5
    assert rvol(150, 0) == 0.0

def test_session_vwap_typical_price_weighted():
    # one bar typical=(12+8+10)/3=10, vol=100 -> vwap=10
    bars = [_bar(0, 9, 12, 8, 10, v=100)]
    assert session_vwap(bars) == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indicators.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.indicators'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/indicators.py
from __future__ import annotations
from execution.models import Bar


def true_range(curr: Bar, prev: Bar) -> float:
    return max(curr.h - curr.l, abs(curr.h - prev.c), abs(curr.l - prev.c))


def atr(bars: list[Bar], length: int) -> float:
    """Simple mean of True Range over the last `length` bars (needs length+1 bars)."""
    if len(bars) < length + 1:
        raise ValueError("need length+1 bars for ATR")
    trs = [true_range(bars[k], bars[k - 1]) for k in range(len(bars) - length, len(bars))]
    return sum(trs) / length


def rvol(cum_vol_today: float, avg_cum_vol_to_time: float) -> float:
    if avg_cum_vol_to_time <= 0:
        return 0.0
    return cum_vol_today / avg_cum_vol_to_time


def session_vwap(bars: list[Bar]) -> float:
    num = sum(((b.h + b.l + b.c) / 3) * b.v for b in bars)
    den = sum(b.v for b in bars)
    if den <= 0:
        raise ValueError("zero volume for VWAP")
    return num / den
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_indicators.py -q`
Expected: PASS (4 passed)

---

### Task 5: Sweep detection

**Files:**
- Create: `execution/detect.py`
- Test: `tests/test_detect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_detect.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.detect import penetration_min, detect_bullish_sweep, detect_bearish_sweep

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

PEN = 0.05  # pen_min for these tests

def test_penetration_min_uses_max_of_floor_and_atr_fraction():
    assert penetration_min(atr5=2.0, pen_atr_frac=0.10, min_pen_abs=0.03) == 0.20
    assert penetration_min(atr5=0.1, pen_atr_frac=0.10, min_pen_abs=0.03) == 0.03

def test_bullish_sweep_detected_same_or_next_bar():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5),      # near level
            _bar(1, 100.3, 100.35, 99.80, 100.20)]    # wick to 99.80 (below 99.95), closes 100.20 > level
    c = detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1)
    assert c is not None
    assert c.direction == "long" and c.level_type == "PDL"
    assert c.wick_extreme == 99.80 and c.reentry_index == 1
    assert c.reentry_close == 100.20

def test_no_signal_when_wick_does_not_clear_pen_min():
    level = 100.0
    bars = [_bar(0, 100.1, 100.2, 99.97, 100.05)]  # low 99.97, only 0.03 below < PEN
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_no_signal_when_close_stays_below_level():
    level = 100.0
    bars = [_bar(0, 100.1, 100.2, 99.80, 99.90)]  # swept but close 99.90 < level
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_late_reentry_rejected_when_max_reentry_bars_is_one():
    level = 100.0
    # bar 0 is the only sweep; bars 1 and 2 must NOT themselves pierce (low >= level-PEN=99.95),
    # so the reclaim at bar 2 is out of bar 0's 1-bar window and attributable to no in-window sweep.
    bars = [_bar(0, 100.1, 100.20, 99.80, 99.90),    # sweep at bar 0, closes below
            _bar(1, 99.97, 99.99, 99.96, 99.97),     # not a sweep, still below level
            _bar(2, 100.0, 100.30, 99.96, 100.20)]   # reclaims above but is not itself a sweep
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_sustained_volume_confirms_on_high_window_volume():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(1, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(2, 100.3, 100.35, 99.80, 99.90, v=300),   # sweep, close below
            _bar(3, 99.9, 100.30, 99.85, 100.20, v=500)]   # reentry on high volume
    c = detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1,
                             confirm_vol=True, sustained_window_bars=2,
                             sustained_baseline_bars=2, sustained_mult=1.75)
    # window vol = 300+500=800 ; baseline = avg(100,100)*2 = 200 ; 800 >= 1.75*200 -> ok
    assert c is not None and c.reentry_index == 3

def test_sustained_volume_blocks_on_low_window_volume():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(1, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(2, 100.3, 100.35, 99.80, 99.90, v=100),
            _bar(3, 99.9, 100.30, 99.85, 100.20, v=100)]   # reentry on flat volume
    # window vol = 200 ; baseline = 200 ; 200 >= 1.75*200 is False -> suppressed
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1,
                                confirm_vol=True, sustained_window_bars=2,
                                sustained_baseline_bars=2, sustained_mult=1.75) is None

def test_bearish_sweep_detected():
    level = 200.0
    bars = [_bar(0, 199.7, 200.40, 199.6, 199.80)]  # wick to 200.40 (>200.05), closes 199.80 < level
    c = detect_bearish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1)
    assert c is not None and c.direction == "short" and c.level_type == "PDH"
    assert c.wick_extreme == 200.40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_detect.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.detect'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/detect.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from execution.models import Bar


@dataclass(frozen=True)
class SweepCandidate:
    direction: str          # "long" | "short"
    level_type: str         # "PDL" | "PDH"
    level_price: float
    sweep_index: int
    sweep_ts: datetime
    reentry_index: int
    reentry_ts: datetime
    wick_extreme: float
    reentry_close: float


def penetration_min(atr5: float, pen_atr_frac: float, min_pen_abs: float) -> float:
    return max(min_pen_abs, pen_atr_frac * atr5)


def sustained_volume_ok(bars: list[Bar], end_index: int, *, window: int,
                        baseline_bars: int, mult: float) -> bool:
    """~15-min sustained-volume confirmation on the 5m grid, lookahead-safe.

    Compares the summed volume of the `window` completed bars ending at end_index
    against `mult` x the trailing per-bar average over the `baseline_bars` bars
    immediately before that window. Uses only bars up to end_index (no peeking at an
    unclosed higher-timeframe bar). Insufficient warmup -> cannot confirm -> suppress.
    """
    if end_index + 1 < window + baseline_bars:
        return False
    win = bars[end_index - window + 1: end_index + 1]
    base = bars[end_index - window - baseline_bars + 1: end_index - window + 1]
    vol_window = sum(b.v for b in win)
    avg_bar = sum(b.v for b in base) / baseline_bars
    baseline = avg_bar * window
    return baseline > 0 and vol_window >= mult * baseline


def _scan(bars: list[Bar], level_price: float, side: str, *, pen_min: float,
          max_reentry_bars: int, confirm_vol: bool = False,
          sustained_window_bars: int = 3, sustained_baseline_bars: int = 20,
          sustained_mult: float = 1.75) -> SweepCandidate | None:
    n = len(bars)
    for i in range(n):
        breached = (bars[i].l < level_price - pen_min) if side == "long" \
            else (bars[i].h > level_price + pen_min)
        if not breached:
            continue
        last_j = min(i + max_reentry_bars, n - 1)
        for j in range(i, last_j + 1):
            window = bars[i:j + 1]
            if side == "long":
                wick = min(b.l for b in window)
                reentry = bars[j].c > level_price and wick < level_price - pen_min
            else:
                wick = max(b.h for b in window)
                reentry = bars[j].c < level_price and wick > level_price + pen_min
            if not reentry:
                continue
            if confirm_vol and not sustained_volume_ok(
                    bars, j, window=sustained_window_bars,
                    baseline_bars=sustained_baseline_bars, mult=sustained_mult):
                continue
            return SweepCandidate(
                direction=side,
                level_type="PDL" if side == "long" else "PDH",
                level_price=level_price,
                sweep_index=i, sweep_ts=bars[i].ts,
                reentry_index=j, reentry_ts=bars[j].ts,
                wick_extreme=wick, reentry_close=bars[j].c,
            )
    return None


def detect_bullish_sweep(bars, level_price, **kw) -> SweepCandidate | None:
    return _scan(bars, level_price, "long", **kw)


def detect_bearish_sweep(bars, level_price, **kw) -> SweepCandidate | None:
    return _scan(bars, level_price, "short", **kw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_detect.py -q`
Expected: PASS (8 passed)

---

### Task 6: RS/RW filter

**Files:**
- Create: `execution/filters.py`
- Test: `tests/test_filters_rs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filters_rs.py
from execution.filters import relative_strength

# rs_thresh/bench_flat_max are FRACTIONS (0.30% -> 0.003, 0.20% -> 0.002)
def test_long_ok_when_outperforms_and_bench_flat():
    r = relative_strength(sym_now=101.0, sym_prev=100.0,   # +1.0%
                          bench_now=100.1, bench_prev=100.0, # +0.1%
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert round(r.rs, 5) == 0.009
    assert r.long_ok is True and r.short_ok is False

def test_long_blocked_when_bench_too_strong():
    r = relative_strength(sym_now=101.0, sym_prev=100.0,
                          bench_now=100.5, bench_prev=100.0,  # +0.5% > flat band
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert r.long_ok is False

def test_short_ok_when_underperforms_and_bench_firm():
    r = relative_strength(sym_now=99.0, sym_prev=100.0,      # -1.0%
                          bench_now=99.9, bench_prev=100.0,   # -0.1%
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert r.short_ok is True and r.long_ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filters_rs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.filters'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/filters.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RSResult:
    rs: float
    ret_sym: float
    ret_bench: float
    long_ok: bool
    short_ok: bool


def relative_strength(*, sym_now: float, sym_prev: float, bench_now: float,
                      bench_prev: float, rs_thresh: float,
                      bench_flat_max: float) -> RSResult:
    if sym_prev <= 0 or bench_prev <= 0:        # halted / just-listed / bad tick -> disqualify
        return RSResult(rs=0.0, ret_sym=0.0, ret_bench=0.0,
                        long_ok=False, short_ok=False)
    ret_sym = sym_now / sym_prev - 1
    ret_bench = bench_now / bench_prev - 1
    rs = ret_sym - ret_bench
    long_ok = rs >= rs_thresh and ret_bench <= bench_flat_max
    short_ok = rs <= -rs_thresh and ret_bench >= -bench_flat_max
    return RSResult(rs=rs, ret_sym=ret_sym, ret_bench=ret_bench,
                    long_ok=long_ok, short_ok=short_ok)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filters_rs.py -q`
Expected: PASS (3 passed)

---

### Task 7: Spread & liquidity filter

**Files:**
- Modify: `execution/filters.py` (append)
- Test: `tests/test_filters_liquidity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filters_liquidity.py
from execution.filters import liquidity_ok

BASE = dict(
    adv_20d=50_000_000, bar_volume=20_000, bar_close=200.0, rvol=1.8,
    bid=199.98, ask=200.02, bid_size=1500, ask_size=1400, risk=0.50,
    min_adv_shares=1_000_000, min_bar_dollar_vol=1_000_000, min_rvol=1.0,
    max_spread_abs=0.05, max_spread_pct=0.0008, min_book_shares=2000,
    spread_risk_frac=0.33,
)

def test_all_checks_pass():
    r = liquidity_ok(**BASE)
    assert r.ok is True
    assert all(r.checks.values())

def test_spread_vs_risk_blocks_tight_stop():
    bad = {**BASE, "risk": 0.10}  # spread 0.04 > 0.33*0.10=0.033
    r = liquidity_ok(**bad)
    assert r.ok is False and r.checks["spread_vs_risk"] is False

def test_low_rvol_blocks():
    r = liquidity_ok(**{**BASE, "rvol": 0.5})
    assert r.ok is False and r.checks["rvol"] is False

def test_optional_book_size_skipped_when_none():
    r = liquidity_ok(**{**BASE, "min_book_shares": None})
    assert r.checks["book"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filters_liquidity.py -q`
Expected: FAIL with `ImportError: cannot import name 'liquidity_ok'`

- [ ] **Step 3: Write minimal implementation (append to `execution/filters.py`)**

```python
@dataclass(frozen=True)
class LiquidityResult:
    ok: bool
    checks: dict


def liquidity_ok(*, adv_20d: float, bar_volume: float, bar_close: float, rvol: float,
                 bid: float, ask: float, bid_size: float, ask_size: float, risk: float,
                 min_adv_shares: float, min_bar_dollar_vol: float, min_rvol: float,
                 max_spread_abs: float, max_spread_pct: float,
                 min_book_shares: float | None, spread_risk_frac: float) -> LiquidityResult:
    spread = ask - bid
    mid = (ask + bid) / 2
    checks = {
        "adv": adv_20d >= min_adv_shares,
        "dollar_vol": bar_volume * bar_close >= min_bar_dollar_vol,
        "rvol": rvol >= min_rvol,
        "spread": spread <= max_spread_abs or (mid > 0 and spread / mid <= max_spread_pct),
        "book": (min_book_shares is None) or (bid_size + ask_size >= min_book_shares),
        "spread_vs_risk": risk > 0 and spread <= spread_risk_frac * risk,
    }
    return LiquidityResult(ok=all(checks.values()), checks=checks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filters_liquidity.py -q`
Expected: PASS (4 passed)

---

### Task 8: R:R filter (asymmetric wick-stop)

**Files:**
- Modify: `execution/filters.py` (append)
- Test: `tests/test_filters_rr.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filters_rr.py
from execution.filters import risk_reward

def test_long_rr_with_wick_stop():
    # entry 100.20, wick_extreme 99.80, buffer=max(0.02, 0.05*atr, spread)
    r = risk_reward(direction="long", entry=100.20, wick_extreme=99.80, target=102.00,
                    atr5=1.0, current_spread=0.03, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer = max(0.02, 0.05, 0.03) = 0.05 -> stop 99.75 ; risk 0.45 ; reward 1.80 ; rr 4.0
    assert r.buffer == 0.05 and round(r.stop, 2) == 99.75
    assert round(r.risk, 2) == 0.45 and round(r.reward, 2) == 1.80
    assert round(r.rr, 2) == 4.0 and r.rr_ok is True

def test_short_rr_with_wick_stop():
    r = risk_reward(direction="short", entry=199.80, wick_extreme=200.40, target=198.00,
                    atr5=1.0, current_spread=0.02, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer=max(0.02,0.05,0.02)=0.05 -> stop 200.45 ; risk 0.65 ; reward 1.80 ; rr ~2.77
    assert round(r.stop, 2) == 200.45 and r.rr_ok is True

def test_rr_below_threshold_fails():
    r = risk_reward(direction="long", entry=100.20, wick_extreme=99.80, target=100.80,
                    atr5=1.0, current_spread=0.03, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer 0.05, risk 0.45, reward 0.60, rr ~1.33 < 2
    assert r.rr_ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filters_rr.py -q`
Expected: FAIL with `ImportError: cannot import name 'risk_reward'`

- [ ] **Step 3: Write minimal implementation (append to `execution/filters.py`)**

```python
@dataclass(frozen=True)
class RRResult:
    entry: float
    stop: float
    target: float
    buffer: float
    risk: float
    reward: float
    rr: float
    rr_ok: bool


def risk_reward(*, direction: str, entry: float, wick_extreme: float, target: float,
                atr5: float, current_spread: float, buf_abs: float, buf_atr_frac: float,
                min_rr: float) -> RRResult:
    """Asymmetric wick-stop: stop sits exactly behind the sweep wick extreme.
    buffer is the max of the abs floor, an ATR fraction, and the live spread, so the
    stop is never tighter than execution noise can justify.
    """
    buffer = max(buf_abs, buf_atr_frac * atr5, current_spread)
    if direction == "long":
        stop = wick_extreme - buffer
    else:
        stop = wick_extreme + buffer
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0.0
    return RRResult(entry=entry, stop=stop, target=target, buffer=buffer,
                    risk=risk, reward=reward, rr=rr, rr_ok=risk > 0 and rr >= min_rr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filters_rr.py -q`
Expected: PASS (3 passed)

---

### Task 9: Signal assembly + qualification

**Files:**
- Create: `execution/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_signals.py
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult
from execution.signals import make_signal_id, build_signal

def _candidate():
    ts_sweep = datetime.fromisoformat("2026-06-04T14:30:00-04:00")
    ts_re = datetime.fromisoformat("2026-06-04T14:35:00-04:00")
    return SweepCandidate(direction="long", level_type="PDL", level_price=187.40,
                          sweep_index=0, sweep_ts=ts_sweep, reentry_index=1,
                          reentry_ts=ts_re, wick_extreme=187.05, reentry_close=187.55)

def test_make_signal_id_format():
    ts = datetime.fromisoformat("2026-06-04T14:35:00-04:00")
    assert make_signal_id("AAPL", "PDL", ts) == "AAPL-PDL-20260604T1435"

def test_build_signal_qualified_when_all_pass():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=190.10, buffer=0.07,
                  risk=0.57, reward=2.55, rr=4.47, rr_ok=True)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={"vwap": 188.30},
                       killzone="ny_open", mode="live", htf_trend="up")
    assert sig.qualified is True and sig.direction == "long"
    d = sig.to_dict()
    assert d["entry_price"] == 187.55 and d["sweep_time"] == "2026-06-04T14:30:00-04:00"
    assert d["rr"] == 4.47 and d["qualified"] is True and d["htf_bias"] == "up"

def test_build_signal_blocked_when_1h_trend_opposes():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=190.10, buffer=0.07,
                  risk=0.57, reward=2.55, rr=4.47, rr_ok=True)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={}, killzone="ny_open",
                       htf_trend="down")   # long setup but 1h trend down -> blocked
    assert sig.qualified is False

def test_build_signal_not_qualified_when_rr_fails():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=188.00, buffer=0.07,
                  risk=0.57, reward=0.45, rr=0.79, rr_ok=False)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={}, killzone="ny_open")
    assert sig.qualified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_signals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.signals'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/signals.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult


@dataclass
class Signal:
    signal_id: str
    symbol: str
    direction: str
    level_type: str
    level_price: float
    sweep_time: datetime
    reentry_time: datetime
    wick_extreme: float
    entry_price: float
    stop_price: float
    target_price: float
    alt_targets: dict
    risk: float
    reward: float
    rr: float
    rs_score: float
    rs_window_min: int
    benchmark: str
    spread_bps: float
    spread_abs: float
    volume_context: dict
    htf_bias: object
    killzone: str
    mode: str
    qualified: bool

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id, "symbol": self.symbol,
            "direction": self.direction, "level_type": self.level_type,
            "level_price": self.level_price,
            "sweep_time": self.sweep_time.isoformat(),
            "reentry_time": self.reentry_time.isoformat(),
            "wick_extreme": self.wick_extreme, "entry_price": self.entry_price,
            "stop_price": self.stop_price, "target_price": self.target_price,
            "alt_targets": self.alt_targets, "risk": self.risk,
            "reward": self.reward, "rr": self.rr, "rs_score": self.rs_score,
            "rs_window_min": self.rs_window_min, "benchmark": self.benchmark,
            "spread_bps": self.spread_bps, "spread_abs": self.spread_abs,
            "volume_context": self.volume_context, "htf_bias": self.htf_bias,
            "killzone": self.killzone, "mode": self.mode, "qualified": self.qualified,
        }


def make_signal_id(symbol: str, level_type: str, reentry_ts: datetime) -> str:
    return f"{symbol}-{level_type}-{reentry_ts.strftime('%Y%m%dT%H%M')}"


def build_signal(*, candidate: SweepCandidate, symbol: str, rs: RSResult,
                 liquidity: LiquidityResult, rr: RRResult, benchmark: str,
                 rs_window_min: int, spread_abs: float, spread_bps: float,
                 volume_context: dict, alt_targets: dict, killzone: str,
                 mode: str = "live", htf_trend: str | None = None) -> Signal:
    direction = candidate.direction
    rs_ok = rs.long_ok if direction == "long" else rs.short_ok
    trend_ok = (htf_trend is None
                or (direction == "long" and htf_trend == "up")
                or (direction == "short" and htf_trend == "down"))
    qualified = rs_ok and liquidity.ok and rr.rr_ok and trend_ok
    return Signal(
        signal_id=make_signal_id(symbol, candidate.level_type, candidate.reentry_ts),
        symbol=symbol, direction=direction, level_type=candidate.level_type,
        level_price=candidate.level_price, sweep_time=candidate.sweep_ts,
        reentry_time=candidate.reentry_ts, wick_extreme=candidate.wick_extreme,
        entry_price=rr.entry, stop_price=rr.stop, target_price=rr.target,
        alt_targets=alt_targets, risk=rr.risk, reward=rr.reward, rr=rr.rr,
        rs_score=rs.rs, rs_window_min=rs_window_min, benchmark=benchmark,
        spread_bps=spread_bps, spread_abs=spread_abs, volume_context=volume_context,
        htf_bias=htf_trend, killzone=killzone, mode=mode, qualified=qualified,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_signals.py -q`
Expected: PASS (4 passed)

---

### Task 10: HTF 1-hour trend filter

**Files:**
- Create: `execution/trend.py`
- Test: `tests/test_trend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trend.py
from execution.trend import ema, htf_trend

def test_ema_seeds_with_sma_then_updates():
    # length 3: seed = mean(10,11,12)=11 ; k=0.5 ; e = 13*0.5 + 11*0.5 = 12
    assert ema([10, 11, 12, 13], 3) == 12.0

def test_trend_up_when_last_close_above_ema():
    assert htf_trend([10, 10, 10, 10, 20], ema_len=3) == "up"

def test_trend_down_when_last_close_below_ema():
    assert htf_trend([20, 20, 20, 20, 5], ema_len=3) == "down"

def test_trend_flat_when_insufficient_history():
    assert htf_trend([10, 11], ema_len=5) == "flat"

def test_require_slope_rejects_when_ema_not_rising():
    # downtrend with a small last bounce: not a valid 'up'
    assert htf_trend([30, 20, 15, 12, 13], ema_len=3, require_slope=True) in ("flat", "down")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trend.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.trend'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/trend.py
from __future__ import annotations


def ema(values: list[float], length: int) -> float:
    """EMA seeded with the SMA of the first `length` values."""
    if len(values) < length:
        raise ValueError("need at least `length` values for EMA")
    k = 2 / (length + 1)
    e = sum(values[:length]) / length
    for v in values[length:]:
        e = v * k + e * (1 - k)
    return e


def htf_trend(closed_1h_closes: list[float], *, ema_len: int,
              require_slope: bool = False) -> str:
    """1-hour trend from COMPLETED 1h closes -> 'up' | 'down' | 'flat'.

    Lookahead-safe: the caller passes only closed 1h bars (the forming 1h bar is
    excluded), so this never peeks at an unfinished higher-timeframe candle.
    """
    need = ema_len + (1 if require_slope else 0)
    if len(closed_1h_closes) < need:
        return "flat"
    e_now = ema(closed_1h_closes, ema_len)
    last = closed_1h_closes[-1]
    if require_slope:
        e_prev = ema(closed_1h_closes[:-1], ema_len)
        if last > e_now and e_now > e_prev:
            return "up"
        if last < e_now and e_now < e_prev:
            return "down"
        return "flat"
    if last > e_now:
        return "up"
    if last < e_now:
        return "down"
    return "flat"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trend.py -q`
Expected: PASS (5 passed)

---

### Task 11: Params config

**Files:**
- Create: `execution/params.yaml`
- Create: `execution/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from execution.config import load_params

def test_defaults_match_spec():
    p = load_params()
    assert p["rs"]["rs_thresh"] == 0.003          # 0.30% as a fraction
    assert p["rs"]["bench_flat_max"] == 0.002
    assert p["rr"]["min_rr"] == 2.0
    assert p["detection"]["max_reentry_bars"] == 1
    assert p["detection"]["confirm_vol"] is False
    assert p["detection"]["sustained_mult"] == 1.75
    assert p["liquidity"]["max_spread_pct"] == 0.0008
    assert p["policy"]["rearm"] == "every_sweep"
    assert p["trend"]["htf_trend_gate"] is True
    assert p["trend"]["htf_ema_len"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.config'`

- [ ] **Step 3: Write minimal implementation**

Create `execution/params.yaml` (fractions for returns/spreads; USD for price buffers):

```yaml
detection:
  operating_tf: "5m"
  tick_cadence: "1m"
  levels: ["PDH", "PDL"]
  level_session: "RTH"
  atr_len: 14
  pen_atr_frac: 0.10
  min_pen_abs: 0.03        # USD (spec: min_pen_ticks)
  max_reentry_bars: 1
  confirm_vol: false
  sustained_window_bars: 3
  sustained_baseline_bars: 20
  sustained_mult: 1.75
  prox_atr_frac: 0.5
rs:
  rs_window_min: 20
  rs_thresh: 0.003         # 0.30%
  bench_flat_max: 0.002    # 0.20%
  bench_default: "SPY"
  rs_must_beat_both: false
liquidity:
  min_adv_shares: 1000000
  min_bar_dollar_vol: 1000000
  min_rvol: 1.0
  max_spread_abs: 0.05
  max_spread_pct: 0.0008   # 8 bps
  min_book_shares: 2000
  spread_risk_frac: 0.33
rr:
  entry_mode: "reentry_close"
  buf_abs: 0.02            # USD (spec: buf_ticks)
  buf_atr_frac: 0.05
  target: "opposite_PD"
  min_rr: 2.0
trend:
  htf_trend_gate: true     # ON for v1: longs need 1h up, shorts 1h down
  htf_ema_len: 20          # EMA on COMPLETED 1h closes (lookahead-safe)
  htf_require_slope: false
policy:
  rearm: "every_sweep"
  cooldown_bars: 0
  session_window: ["09:30", "16:00"]
  killzones: [["09:30", "11:30"], ["14:00", "15:30"]]
universe:
  inplay_max: 40
```

Create `execution/config.py`:

```python
# execution/config.py
from __future__ import annotations
from pathlib import Path
import yaml

_DEFAULT = Path(__file__).with_name("params.yaml")


def load_params(path: str | Path = _DEFAULT) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -q`
Expected: PASS (1 passed)

---

### Task 12: Full-suite checkpoint

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run: `pytest -q`
Expected: PASS — **39 passed**, 0 failed. (36 from the tasks above + 3 review-hardening tests: RS zero-price guard, `htf_trend="flat"` blocks qualification, `require_slope` confirms "up".)

- [ ] **Step 2: Lookahead-audit confirmation**

Confirm `tests/test_levels.py::test_uses_prior_completed_day_only` is green — this is the standing assertion that levels never derive from the forming session.

- [ ] **Step 3: Report to user (no commit)**

Summarize: modules built, test count green, and that per the commit policy we now pause for user sign-off before `git init` + first commit.

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-06-04-liquidity-sweep-scanner-design.md`):
- Lookahead-safe levels → Task 3 ✅ (+ standing audit in Task 11)
- Sweep detection pseudo-code (bull/bear, pen_min, max_reentry, ~15m sustained-vol gate) → Task 5 ✅
- RS/RW formula → Task 6 ✅
- Spread & liquidity boolean (incl. spread-vs-risk tie) → Task 7 ✅
- R:R with asymmetric wick-stop → Task 8 ✅
- Signal JSON schema + qualify (incl. 1h trend gate) → Task 9 ✅
- HTF 1-hour trend gate (lookahead-safe, ON for v1) → Task 10 ✅
- params.yaml single source of truth → Task 11 ✅
- ATR/RVOL/VWAP used by detection & filters → Task 4 ✅
- *Deferred to later-phase plans (intentionally out of scope here):* universe pre-filter (Phase 3), backtest harness (Phase 2), state machine + live loop (Phase 3), dashboard (Phase 4), execution seam (Phase 5), Questrade data client. Noted so the gap is deliberate, not accidental.

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows real assertions. ✅

**3. Type consistency:** `Bar`, `Quote`, `Level`, `SweepCandidate` (with `sweep_ts`/`reentry_ts`), `RSResult`, `LiquidityResult`, `RRResult`, `Signal` are defined once and consumed with matching field names in Task 9 (`build_signal` reads `rr.entry/stop/target/risk/reward/rr/rr_ok`, `rs.long_ok/short_ok/rs`, `liquidity.ok`). Units fixed: fractions for returns/spreads, USD for `min_pen_abs`/`buf_abs`. ✅

---

## Next phases (separate plans, written after this core is green)
- **Phase 2 — Backtest harness:** universe candidate list, lookahead-safe replay, 1m path resolution, stats + slices.
- **Phase 3 — Live scanner:** Questrade data client, in-play pre-filter, per-symbol state machine, 1m polling loop emitting signals.
- **Phase 4 — Dashboard:** WebSocket server + React table/chart preview.
- **Phase 5 — Execution seam:** hand qualified signals to the existing `tv-mcp` rails (approval-gated).
- **Phase 0 (optional, interactive):** Pine sandbox visual proof via the TradingView MCP.
