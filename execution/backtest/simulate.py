from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from execution.models import Bar


@dataclass
class Trade:
    symbol: str
    direction: str
    level_type: str
    entry_time: datetime
    entry_price: float
    stop: float
    target: float
    exit_time: datetime
    exit_price: float
    exit_reason: str        # "target" | "stop" | "timeout"
    r_multiple: float
    bars_held: int
    killzone: str
    rs_score: float


def _r(direction: str, entry: float, exit_price: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    return (exit_price - entry) / risk if direction == "long" else (entry - exit_price) / risk


def simulate_trade(*, direction: str, level_type: str, symbol: str, entry_time: datetime,
                   entry_price: float, stop: float, target: float, forward_bars: list[Bar],
                   killzone: str = "", rs_score: float = 0.0) -> Trade:
    """Walk forward bars; exit at first of stop/target. A bar that straddles both
    resolves stop-first (conservative). No hit by the end -> timeout at last close.
    """
    risk = abs(entry_price - stop)

    def make(exit_time, exit_price, reason, held):
        return Trade(symbol=symbol, direction=direction, level_type=level_type,
                     entry_time=entry_time, entry_price=entry_price, stop=stop, target=target,
                     exit_time=exit_time, exit_price=exit_price, exit_reason=reason,
                     r_multiple=_r(direction, entry_price, exit_price, risk),
                     bars_held=held, killzone=killzone, rs_score=rs_score)

    if not forward_bars:
        return make(entry_time, entry_price, "timeout", 0)

    for k, bar in enumerate(forward_bars, start=1):
        if direction == "long":
            hit_stop, hit_tgt = bar.l <= stop, bar.h >= target
        else:
            hit_stop, hit_tgt = bar.h >= stop, bar.l <= target
        if hit_stop:                       # stop-first on straddle
            return make(bar.ts, stop, "stop", k)
        if hit_tgt:
            return make(bar.ts, target, "target", k)

    last = forward_bars[-1]
    return make(last.ts, last.c, "timeout", len(forward_bars))
