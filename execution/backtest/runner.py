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
