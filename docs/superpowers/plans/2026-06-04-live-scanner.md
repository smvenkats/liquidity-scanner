# Live Scanner (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure, testable live-scanner engine: an in-play universe pre-filter, a per-symbol state machine that emits each qualified sweep exactly once as bars arrive, and a thin `scan_once` driver — all behind a pluggable feed interface, reusing Phase 1 + Phase 2 logic.

**Architecture:** Extract the candidate→Signal qualification out of the Phase 2 runner into a shared `execution/pipeline.py` (so backtest and live qualify identically). Add `execution/scanner/` with the universe pre-filter, the stateful `SymbolScanner` (dedup by signal_id), `scan_once`, and a JSONL sink. The engine depends only on a feed object exposing `.bars(symbol, tf)` (BarStore satisfies it; a live adapter or a stub both work). No always-on loop and no direct broker client in v1 — the "loop" is repeated `scan_once` calls (agent/cron now, Phase 4 dashboard later).

**Tech Stack:** Python 3.11+, `pytest`, `pyyaml`. Reuses `execution/` (Phase 1) and `execution/backtest/` helpers unchanged.

---

## ⚠️ Commit policy
No `git init`/`commit` during these tasks beyond what already exists — **do not create new commits.** Each task's checkpoint is a green test run. We commit once at the end, after the suite is green and the user signs off.

## Decisions (locked)
- **Runtime:** pluggable engine + `scan_once` driver. Feed is any object with `.bars(symbol, tf)`.
- **Scope:** signal emission only (JSONL sink). WebSocket/dashboard is Phase 4.
- **State machine:** realized as a stateful incremental emitter — on each update it re-detects the session's sweeps and emits only signal_ids not yet seen. `proximity_state` reports IDLE/WATCHING for observability (display), without driving the emit logic (YAGNI vs a full FSM).
- **DRY:** Phase 2 runner is refactored to call the shared `qualify_candidate`; its existing tests are the regression guard.

## File structure
| File | Responsibility |
|---|---|
| `execution/pipeline.py` | `ScanContext` + `qualify_candidate` (shared by backtest + live) |
| `execution/backtest/runner.py` | **refactored** to call `qualify_candidate` (behavior unchanged) |
| `execution/scanner/__init__.py` | package marker (empty) |
| `execution/scanner/universe.py` | `is_inplay`, `select_inplay` (daily-data pre-filter) |
| `execution/scanner/engine.py` | `SymbolScanner`, `scan_once`, `proximity_state` |
| `execution/scanner/sink.py` | `emit_signals` (append JSONL) |
| `directives/run_scanner.md` | SOP (created in final task, not TDD) |
| `tests/test_pipeline.py`, `tests/test_scan_*.py` | new tests |

---

### Task 1: Shared qualification pipeline

**Files:**
- Create: `execution/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
from datetime import datetime, timedelta
from execution.models import Bar, Level
from execution.detect import detect_bullish_sweep, penetration_min
from execution.indicators import atr
from execution.pipeline import ScanContext, qualify_candidate

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

def _ctx(trend_gate=True):
    s = datetime(2026, 6, 4, 13, 30)
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    sess = [_b(s, 99.20, 99.40, 99.10, 99.30),
            _b(s + timedelta(minutes=5), 99.30, 99.50, 99.20, 99.40),
            _b(s + timedelta(minutes=10), 99.40, 99.60, 99.30, 99.50),
            _b(s + timedelta(minutes=15), 99.50, 99.70, 99.40, 99.60),
            _b(s + timedelta(minutes=20), 99.60, 99.80, 98.50, 99.70, v=2_000_000)]
    bars5 = warm + sess
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in bars5]
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000)]
    from execution.config import load_params
    p = load_params()
    atr5 = atr(warm, p["detection"]["atr_len"])
    return ScanContext(symbol="ABC", bars5=bars5, bench5=bench5, h1=h1,
                       adv=80_000_000, atr5=atr5, levels=Level(110.0, 99.0, None),
                       params=p, benchmark="SPY", trend_gate=trend_gate, mode="live"), sess, atr5, p

def test_qualifies_a_clean_long_sweep():
    ctx, sess, atr5, p = _ctx(trend_gate=True)
    pen = penetration_min(atr5, p["detection"]["pen_atr_frac"], p["detection"]["min_pen_abs"])
    c = detect_bullish_sweep(sess, ctx.levels.pdl, pen_min=pen,
                             max_reentry_bars=p["detection"]["max_reentry_bars"])
    sig = qualify_candidate(c, ctx)
    assert sig.qualified is True and sig.direction == "long"
    assert sig.target_price == 110.0 and sig.htf_bias == "up"

def test_trend_gate_off_changes_nothing_for_aligned_trend():
    ctx, sess, atr5, p = _ctx(trend_gate=False)
    pen = penetration_min(atr5, p["detection"]["pen_atr_frac"], p["detection"]["min_pen_abs"])
    c = detect_bullish_sweep(sess, ctx.levels.pdl, pen_min=pen,
                             max_reentry_bars=p["detection"]["max_reentry_bars"])
    sig = qualify_candidate(c, ctx)
    assert sig.qualified is True and sig.htf_bias is None   # gate off -> no trend stored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/pipeline.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import timedelta

from execution.models import Bar, Level
from execution.filters import relative_strength, liquidity_ok, risk_reward, RSResult
from execution.trend import htf_trend
from execution.signals import build_signal, Signal
from execution.detect import SweepCandidate
from execution.backtest.features import (
    modeled_spread, rvol_from_adv, close_now_prev, killzone)


@dataclass
class ScanContext:
    symbol: str
    bars5: list          # continuous 5m series (for RS lookback)
    bench5: list         # benchmark 5m series
    h1: list             # 1h series (for trend)
    adv: float
    atr5: float
    levels: Level
    params: dict
    benchmark: str = "SPY"
    trend_gate: bool = True
    mode: str = "live"


def qualify_candidate(candidate: SweepCandidate, ctx: ScanContext) -> Signal:
    """Run the full probability stack on one sweep candidate and assemble a Signal.

    Shared by the backtest runner and the live scanner so they qualify identically.
    Spread is MODELED (no historical/live L1 in v1); RS is real off the aligned
    benchmark; the 1h-trend gate is applied unless trend_gate is False.
    """
    p = ctx.params
    rsd, liqd, rrd, trd = p["rs"], p["liquidity"], p["rr"], p["trend"]
    direction = candidate.direction
    target = ctx.levels.pdh if direction == "long" else ctx.levels.pdl

    spread = modeled_spread(candidate.reentry_close, ctx.adv)
    rr_res = risk_reward(direction=direction, entry=candidate.reentry_close,
                         wick_extreme=candidate.wick_extreme, target=target, atr5=ctx.atr5,
                         current_spread=spread, buf_abs=rrd["buf_abs"],
                         buf_atr_frac=rrd["buf_atr_frac"], min_rr=rrd["min_rr"])

    sp = close_now_prev(ctx.bars5, candidate.reentry_ts, rsd["rs_window_min"])
    bp = close_now_prev(ctx.bench5, candidate.reentry_ts, rsd["rs_window_min"])
    if sp and bp:
        rs_res = relative_strength(sym_now=sp[0], sym_prev=sp[1], bench_now=bp[0],
                                   bench_prev=bp[1], rs_thresh=rsd["rs_thresh"],
                                   bench_flat_max=rsd["bench_flat_max"])
    else:
        rs_res = RSResult(0.0, 0.0, 0.0, False, False)

    reentry_bar = next((b for b in ctx.bars5 if b.ts == candidate.reentry_ts), None)
    bar_vol = reentry_bar.v if reentry_bar else 0.0
    rvol = rvol_from_adv(bar_vol, ctx.adv)
    mid = candidate.reentry_close
    liq_res = liquidity_ok(
        adv_20d=ctx.adv, bar_volume=bar_vol, bar_close=candidate.reentry_close, rvol=rvol,
        bid=mid - spread / 2, ask=mid + spread / 2, bid_size=1e9, ask_size=1e9,
        risk=rr_res.risk, min_adv_shares=liqd["min_adv_shares"],
        min_bar_dollar_vol=liqd["min_bar_dollar_vol"], min_rvol=liqd["min_rvol"],
        max_spread_abs=liqd["max_spread_abs"], max_spread_pct=liqd["max_spread_pct"],
        min_book_shares=None, spread_risk_frac=liqd["spread_risk_frac"])

    if ctx.trend_gate:
        closed = [b.c for b in ctx.h1 if b.ts + timedelta(hours=1) <= candidate.reentry_ts]
        trend = htf_trend(closed, ema_len=trd["htf_ema_len"], require_slope=trd["htf_require_slope"])
    else:
        trend = None

    return build_signal(
        candidate=candidate, symbol=ctx.symbol, rs=rs_res, liquidity=liq_res, rr=rr_res,
        benchmark=ctx.benchmark, rs_window_min=rsd["rs_window_min"], spread_abs=spread,
        spread_bps=spread / mid * 10_000 if mid else 0.0,
        volume_context={"rvol": rvol, "adv": ctx.adv}, alt_targets={},
        killzone=killzone(candidate.reentry_ts), mode=ctx.mode, htf_trend=trend)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -q`
Expected: PASS (2 passed)

---

### Task 2: Refactor the backtest runner onto the shared pipeline

**Files:**
- Modify: `execution/backtest/runner.py` (replace inline qualification with `qualify_candidate`)

- [ ] **Step 1: Replace the file contents**

Rewrite `execution/backtest/runner.py` to:

```python
# execution/backtest/runner.py
from __future__ import annotations

from execution.levels import previous_session_levels
from execution.indicators import atr
from execution.detect import penetration_min, detect_bullish_sweep, detect_bearish_sweep
from execution.config import load_params
from execution.pipeline import ScanContext, qualify_candidate
from execution.backtest.features import adv_from_daily
from execution.backtest.replay import find_all_sweeps
from execution.backtest.simulate import simulate_trade
from execution.backtest.stats import summarize, slice_by


def run_backtest(symbols, store, *, params=None, benchmark="SPY", trend_gate=True) -> dict:
    p = params or load_params()
    d = p["detection"]
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
            ctx = ScanContext(symbol=sym, bars5=bars5, bench5=bench5, h1=h1, adv=adv,
                              atr5=atr5, levels=lvl, params=p, benchmark=benchmark,
                              trend_gate=trend_gate, mode="backtest")

            sides = [(detect_bullish_sweep, lvl.pdl), (detect_bearish_sweep, lvl.pdh)]
            for fn, level in sides:
                for c in find_all_sweeps(sess, level, fn, pen_min=pen,
                                         max_reentry_bars=d["max_reentry_bars"]):
                    sig = qualify_candidate(c, ctx)
                    if not sig.qualified:
                        continue
                    forward = [b for b in sess if b.ts > c.reentry_ts]
                    trades.append(simulate_trade(
                        direction=c.direction, level_type=c.level_type, symbol=sym,
                        entry_time=c.reentry_ts, entry_price=sig.entry_price, stop=sig.stop_price,
                        target=sig.target_price, forward_bars=forward,
                        killzone=sig.killzone, rs_score=sig.rs_score))

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

- [ ] **Step 2: Run the Phase 2 regression suite**

Run: `pytest tests/test_bt_runner.py tests/test_bt_simulate.py tests/test_bt_stats.py -q`
Expected: PASS — same results as before the refactor (the runner integration test still produces the crafted winning trade). Behavior is unchanged; only the qualification call site moved.

- [ ] **Step 3: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: PASS — still **60 passed** (Phase 1 + Phase 2), plus the 2 new pipeline tests = **62 passed**, 0 failed.

---

### Task 3: In-play universe pre-filter

**Files:**
- Create: `execution/scanner/__init__.py` (empty)
- Create: `execution/scanner/universe.py`
- Test: `tests/test_scan_universe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_universe.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.config import load_params
from execution.scanner.universe import is_inplay, select_inplay

P = load_params()

def _b(ts, o, h, l, c, v=80_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

def _liquid_daily():
    return [_b(datetime(2026, 6, 2), 100, 110, 99, 100),
            _b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100)]

def _gapped_session():   # opens 3% below prior close 100 -> gap in play
    s = datetime(2026, 6, 4, 13, 30)
    return [_b(s + timedelta(minutes=5 * i), 97, 97.2, 96.8, 97, v=500_000) for i in range(20)]

class Feed:
    def __init__(self, data): self._d = data
    def bars(self, sym, tf): return self._d.get((sym, tf), [])

def test_gapped_liquid_name_is_in_play():
    bars5 = _gapped_session()
    assert is_inplay(_liquid_daily(), bars5, P) is True

def test_cheap_name_excluded():
    cheap = [_b(datetime(2026, 6, 4, 13, 30) + timedelta(minutes=5 * i), 3, 3.1, 2.9, 3) for i in range(20)]
    assert is_inplay(_liquid_daily(), cheap, P) is False

def test_illiquid_name_excluded():
    thin_daily = [_b(datetime(2026, 6, 2), 100, 110, 99, 100, v=100_000),
                  _b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=100_000)]
    assert is_inplay(thin_daily, _gapped_session(), P) is False

def test_select_inplay_filters_and_caps():
    feed = Feed({("AAA", "1d"): _liquid_daily(), ("AAA", "5m"): _gapped_session(),
                 ("BBB", "1d"): _liquid_daily(),
                 ("BBB", "5m"): [_b(datetime(2026, 6, 4, 13, 30), 100, 100.1, 99.9, 100)]})
    picked = select_inplay(["AAA", "BBB"], feed, P)
    assert "AAA" in picked and "BBB" not in picked   # BBB neither gapped nor near a level
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_universe.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.scanner.universe'`

- [ ] **Step 3: Write minimal implementation**

Create empty `execution/scanner/__init__.py`, then `execution/scanner/universe.py`:

```python
# execution/scanner/universe.py
from __future__ import annotations
from execution.levels import previous_session_levels
from execution.indicators import atr
from execution.backtest.features import adv_from_daily


def is_inplay(daily, bars5, params) -> bool:
    """Pre-filter: liquid enough AND (gapped OR sitting near a prior-day level)."""
    u = params["universe"]
    if len(daily) < 2 or not bars5:
        return False
    today = max(b.ts.date() for b in bars5)
    sess = [b for b in bars5 if b.ts.date() == today]
    if not sess:
        return False
    price = sess[-1].c
    prev_close = daily[-2].c if daily[-1].ts.date() >= today else daily[-1].c
    if price < u["min_price"] or adv_from_daily(daily) < u["min_adv_shares"]:
        return False
    gap = abs(sess[0].o - prev_close) / prev_close if prev_close else 0.0
    try:
        lvl = previous_session_levels(daily, today)
    except ValueError:
        return gap >= u["gap_pct"]
    pre = [b for b in bars5 if b.ts.date() < today]
    atr5 = atr(pre, params["detection"]["atr_len"]) if len(pre) >= params["detection"]["atr_len"] + 1 else 0.0
    band = u["near_level_atr"] * atr5
    near = abs(price - lvl.pdh) <= band or abs(price - lvl.pdl) <= band
    return gap >= u["gap_pct"] or near


def select_inplay(symbols, feed, params) -> list:
    picked = [s for s in symbols if is_inplay(feed.bars(s, "1d"), feed.bars(s, "5m"), params)]
    return picked[: params["universe"]["inplay_max"]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan_universe.py -q`
Expected: PASS (4 passed)

---

### Task 4: Scanner engine (state machine + scan_once)

**Files:**
- Create: `execution/scanner/engine.py`
- Test: `tests/test_scan_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_engine.py
from datetime import datetime, timedelta, date
from execution.models import Bar
from execution.config import load_params
from execution.scanner.engine import SymbolScanner, scan_once, proximity_state

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

class Feed:
    def __init__(self, data): self._d = data
    def bars(self, sym, tf): return self._d.get((sym, tf), [])

def _feed():
    s = datetime(2026, 6, 4, 13, 30)
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000),
             _b(datetime(2026, 6, 4), 100, 111, 98, 110, v=80_000_000)]
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    sess = [_b(s, 99.20, 99.40, 99.10, 99.30),
            _b(s + timedelta(minutes=5), 99.30, 99.50, 99.20, 99.40),
            _b(s + timedelta(minutes=10), 99.40, 99.60, 99.30, 99.50),
            _b(s + timedelta(minutes=15), 99.50, 99.70, 99.40, 99.60),
            _b(s + timedelta(minutes=20), 99.60, 99.80, 98.50, 99.70, v=2_000_000)]
    sym5 = warm + sess
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in sym5]
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    return Feed({("ABC", "5m"): sym5, ("ABC", "1d"): daily, ("ABC", "1h"): h1,
                 ("SPY", "5m"): bench5})

def test_emits_qualified_signal_once_then_dedups():
    feed, P = _feed(), load_params()
    states = {}
    first = scan_once(["ABC"], feed, states, P, benchmark="SPY")
    assert len(first) == 1 and first[0].symbol == "ABC" and first[0].qualified
    second = scan_once(["ABC"], feed, states, P, benchmark="SPY")   # same bars
    assert second == []                                             # already emitted

def test_proximity_state_reports_watching_near_level():
    P = load_params()
    # price 99.05 within 0.5*atr of PDL 99.0
    assert proximity_state(99.05, levels_pdh=110.0, levels_pdl=99.0, atr5=1.0, params=P) == "WATCHING"
    assert proximity_state(105.0, levels_pdh=110.0, levels_pdl=99.0, atr5=1.0, params=P) == "IDLE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.scanner.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/scanner/engine.py
from __future__ import annotations
from execution.levels import previous_session_levels
from execution.indicators import atr
from execution.detect import penetration_min, detect_bullish_sweep, detect_bearish_sweep
from execution.config import load_params
from execution.pipeline import ScanContext, qualify_candidate
from execution.backtest.features import adv_from_daily
from execution.backtest.replay import find_all_sweeps


def proximity_state(price, *, levels_pdh, levels_pdl, atr5, params) -> str:
    band = params["detection"]["prox_atr_frac"] * atr5
    near = abs(price - levels_pdh) <= band or abs(price - levels_pdl) <= band
    return "WATCHING" if near else "IDLE"


class SymbolScanner:
    """Stateful per-symbol scanner. Re-detects the current session's sweeps on each
    update and returns only signals whose id has not been emitted before."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._emitted: set[str] = set()

    def on_update(self, ctx: ScanContext) -> list:
        d = ctx.params["detection"]
        pen = penetration_min(ctx.atr5, d["pen_atr_frac"], d["min_pen_abs"])
        today = max(b.ts.date() for b in ctx.bars5)
        sess = [b for b in ctx.bars5 if b.ts.date() == today]
        out = []
        for fn, level in [(detect_bullish_sweep, ctx.levels.pdl),
                          (detect_bearish_sweep, ctx.levels.pdh)]:
            for c in find_all_sweeps(sess, level, fn, pen_min=pen,
                                     max_reentry_bars=d["max_reentry_bars"]):
                sig = qualify_candidate(c, ctx)
                if sig.qualified and sig.signal_id not in self._emitted:
                    self._emitted.add(sig.signal_id)
                    out.append(sig)
        return out


def scan_once(symbols, feed, states, params=None, *, benchmark="SPY",
              trend_gate=True, mode="live") -> list:
    p = params or load_params()
    d = p["detection"]
    out = []
    for sym in symbols:
        bars5 = feed.bars(sym, "5m")
        daily = feed.bars(sym, "1d")
        h1 = feed.bars(sym, "1h")
        bench5 = feed.bars(benchmark, "5m")
        if not bars5 or not daily:
            continue
        today = max(b.ts.date() for b in bars5)
        try:
            lvl = previous_session_levels(daily, today)
        except ValueError:
            continue
        pre = [b for b in bars5 if b.ts.date() < today]
        if len(pre) < d["atr_len"] + 1:
            continue
        ctx = ScanContext(symbol=sym, bars5=bars5, bench5=bench5, h1=h1,
                          adv=adv_from_daily(daily), atr5=atr(pre, d["atr_len"]),
                          levels=lvl, params=p, benchmark=benchmark,
                          trend_gate=trend_gate, mode=mode)
        scanner = states.setdefault(sym, SymbolScanner(sym))
        out.extend(scanner.on_update(ctx))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan_engine.py -q`
Expected: PASS (2 passed)

---

### Task 5: JSONL signal sink

**Files:**
- Create: `execution/scanner/sink.py`
- Test: `tests/test_scan_sink.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_sink.py
import json
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult
from execution.signals import build_signal
from execution.scanner.sink import emit_signals

def _sig():
    ts = datetime.fromisoformat("2026-06-04T14:20:00-04:00")
    c = SweepCandidate(direction="long", level_type="PDL", level_price=99.0, sweep_index=0,
                       sweep_ts=ts, reentry_index=0, reentry_ts=ts, wick_extreme=98.5,
                       reentry_close=99.7)
    rs = RSResult(0.004, 0.005, 0.001, True, False)
    liq = LiquidityResult(True, {})
    rr = RRResult(99.7, 98.48, 110.0, 0.02, 1.22, 10.3, 8.4, True)
    return build_signal(candidate=c, symbol="ABC", rs=rs, liquidity=liq, rr=rr, benchmark="SPY",
                        rs_window_min=20, spread_abs=0.01, spread_bps=1.0,
                        volume_context={"rvol": 1.9}, alt_targets={}, killzone="ny_open",
                        mode="live", htf_trend="up")

def test_emit_appends_jsonl(tmp_path):
    path = tmp_path / "signals.jsonl"
    emit_signals([_sig()], path)
    emit_signals([_sig()], path)             # append, not overwrite
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["symbol"] == "ABC" and rec["qualified"] is True and rec["target_price"] == 110.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_sink.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution.scanner.sink'`

- [ ] **Step 3: Write minimal implementation**

```python
# execution/scanner/sink.py
from __future__ import annotations
import json
from pathlib import Path


def emit_signals(signals, path) -> int:
    """Append each signal as one JSON line. Returns the count written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig.to_dict()) + "\n")
    return len(signals)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan_sink.py -q`
Expected: PASS (1 passed)

---

### Task 6: Universe params + config

**Files:**
- Modify: `execution/params.yaml` (extend the `universe` group)
- Test: `tests/test_scan_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_config.py
from execution.config import load_params

def test_universe_inplay_thresholds_present():
    u = load_params()["universe"]
    assert u["min_price"] == 5.0
    assert u["min_adv_shares"] == 1_000_000
    assert u["gap_pct"] == 0.01
    assert u["near_level_atr"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_config.py -q`
Expected: FAIL with `KeyError: 'min_price'`

- [ ] **Step 3: Edit `execution/params.yaml`**

Replace the existing `universe:` block (currently `universe:\n  inplay_max: 40`) with:

```yaml
universe:
  inplay_max: 40
  min_price: 5.0
  min_adv_shares: 1000000
  gap_pct: 0.01            # |open - prev_close| / prev_close
  near_level_atr: 0.5      # within 0.5*atr5 of PDH/PDL counts as in-play
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan_config.py -q`
Expected: PASS (1 passed)

---

### Task 7: Directive + full-suite checkpoint

**Files:**
- Create: `directives/run_scanner.md`
- Test: none (verification)

- [ ] **Step 1: Create the directive SOP**

Create `directives/run_scanner.md`:

```markdown
# Directive: Run the Live Scanner

**Goal:** Surface QUALIFIED liquidity-sweep signals on the in-play universe, emitting each once.

**Inputs:** a feed exposing `.bars(symbol, tf)` for 5m/1h/1d (+ benchmark 5m). Now: a BarStore over a directory refreshed by polling tv-mcp `get_ohlcv`. Later: a direct Questrade streaming adapter.

**Tools:**
- `execution/scanner/universe.py` - `select_inplay(symbols, feed, params)` -> today's in-play names.
- `execution/scanner/engine.py` - `scan_once(symbols, feed, states, params)` -> new qualified signals. Persist `states` (dict) across calls so each signal emits once.
- `execution/scanner/sink.py` - `emit_signals(signals, path)` -> append JSONL.

**Loop pattern (driver):**
1. Once at session start: `inplay = select_inplay(candidates, feed, params)`.
2. Every ~1 min: refresh the feed (re-pull recent bars), then `new = scan_once(inplay, feed, states, params)`; `emit_signals(new, "signals.jsonl")`.

**Edge cases / limits:**
- Signal-only: emits decision-support signals; execution stays manual (Phase 5 seam to the tv-mcp rails later).
- Spread is MODELED until a real L1 feed is wired.
- 500-bar feed cap is plenty for live (only recent bars are needed); the constraint matters for backtest, not live.
```

- [ ] **Step 2: Run the entire suite**

Run: `pytest -q`
Expected: PASS — **all green: Phase 1 (39) + Phase 2 (21) + Phase 3 (10) = 70 passed**, 0 failed.
(Phase 3 adds: pipeline 2, universe 4, engine 2, sink 1, config 1.)

- [ ] **Step 3: Report (no commit)**

Summarize new modules + green count; note the live-feed adapter + a real scan-once demo is the operational next step; we still hold git until the user signs off.

---

## Self-Review

**1. Spec coverage** (vs spec state-machine + dashboard-backend sections):
- Per-symbol state machine emitting QUALIFIED signals once → Task 4 (`SymbolScanner` dedup) ✅
- IDLE/WATCHING observability → `proximity_state` ✅
- In-play universe pre-filter → Task 3 ✅
- Signal emission (JSON) → Task 5 ✅
- Reuse of detection + 3 filters + trend gate → shared `qualify_candidate` (Task 1) ✅
- Pluggable feed (BarStore / stub / live adapter) → engine depends only on `.bars()` ✅
- *Deferred intentionally:* WebSocket + dashboard (Phase 4), direct Questrade streaming adapter + always-on loop (operational), real L1 spread. Noted, not gaps.

**2. Placeholder scan:** No TBD/TODO; all code complete.

**3. Type consistency:** `ScanContext`/`qualify_candidate` (Task 1) are consumed identically by the refactored runner (Task 2) and the engine (Task 4). `Signal.signal_id`/`.qualified`/`.to_dict()` reused as defined in Phase 1. `find_all_sweeps`, `penetration_min`, `adv_from_daily`, `previous_session_levels`, `atr` reused unchanged. The runner refactor swaps `sess[c.reentry_index]` volume lookup for `qualify_candidate`'s ts-based lookup — same bar, behavior preserved (guarded by `test_bt_runner`).

---

## Post-review hardening (applied; suite → 72)
Code-quality review (CHANGES-REQUESTED) drove these correctness fixes for live/messy data:
- **`SweepCandidate.reentry_volume`** carried at detection time (`detect.py`); `qualify_candidate` reads it directly instead of re-scanning `bars5` by timestamp — strictly correct regardless of bar ordering / duplicate timestamps.
- **`scan_once(..., as_of_date=None)`** stale-feed guard — skips a symbol whose latest session ≠ the trading date.
- **`BarStore.bars` sorts by timestamp** on load — removes the unstated "files must be chronological" fragility.
- Documented `SymbolScanner._emitted` per-day lifetime. +2 tests (carried-volume path, stale-feed skip).

## Next (after this engine is green)
- **Live-feed adapter + demo:** wrap tv-mcp `get_ohlcv` as a feed, run `select_inplay` then `scan_once` on real names, emit `signals.jsonl`.
- **Phase 4:** WebSocket server + dashboard reading the signal stream.
- **Phase 5:** execution seam to the existing tv-mcp rails (approval-gated).
