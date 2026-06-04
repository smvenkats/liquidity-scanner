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
    if sym_prev <= 0 or bench_prev <= 0:
        return RSResult(rs=0.0, ret_sym=0.0, ret_bench=0.0,
                        long_ok=False, short_ok=False)
    ret_sym = sym_now / sym_prev - 1
    ret_bench = bench_now / bench_prev - 1
    rs = ret_sym - ret_bench
    long_ok = rs >= rs_thresh and ret_bench <= bench_flat_max
    short_ok = rs <= -rs_thresh and ret_bench >= -bench_flat_max
    return RSResult(rs=rs, ret_sym=ret_sym, ret_bench=ret_bench,
                    long_ok=long_ok, short_ok=short_ok)


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
