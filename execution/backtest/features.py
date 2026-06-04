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
