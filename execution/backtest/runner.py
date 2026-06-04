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
