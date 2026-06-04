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
