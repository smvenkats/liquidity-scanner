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
    update and returns only signals whose id has not been emitted before. The `_emitted`
    set lives for the scanner's lifetime; keep one `states` dict per trading day
    (signal_ids include the date, so cross-day reuse is safe but unbounded)."""

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
              trend_gate=True, mode="live", as_of_date=None) -> list:
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
        if as_of_date is not None and today != as_of_date:
            continue
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
