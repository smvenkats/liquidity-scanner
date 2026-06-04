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

    bar_vol = candidate.reentry_volume
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
