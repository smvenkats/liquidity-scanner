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
