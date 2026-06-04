# execution/signals.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult


@dataclass
class Signal:
    signal_id: str
    symbol: str
    direction: str
    level_type: str
    level_price: float
    sweep_time: datetime
    reentry_time: datetime
    wick_extreme: float
    entry_price: float
    stop_price: float
    target_price: float
    alt_targets: dict
    risk: float
    reward: float
    rr: float
    rs_score: float
    rs_window_min: int
    benchmark: str
    spread_bps: float
    spread_abs: float
    volume_context: dict
    htf_bias: object
    killzone: str
    mode: str
    qualified: bool

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id, "symbol": self.symbol,
            "direction": self.direction, "level_type": self.level_type,
            "level_price": self.level_price,
            "sweep_time": self.sweep_time.isoformat(),
            "reentry_time": self.reentry_time.isoformat(),
            "wick_extreme": self.wick_extreme, "entry_price": self.entry_price,
            "stop_price": self.stop_price, "target_price": self.target_price,
            "alt_targets": self.alt_targets, "risk": self.risk,
            "reward": self.reward, "rr": self.rr, "rs_score": self.rs_score,
            "rs_window_min": self.rs_window_min, "benchmark": self.benchmark,
            "spread_bps": self.spread_bps, "spread_abs": self.spread_abs,
            "volume_context": self.volume_context, "htf_bias": self.htf_bias,
            "killzone": self.killzone, "mode": self.mode, "qualified": self.qualified,
        }


def make_signal_id(symbol: str, level_type: str, reentry_ts: datetime) -> str:
    return f"{symbol}-{level_type}-{reentry_ts.strftime('%Y%m%dT%H%M')}"


def build_signal(*, candidate: SweepCandidate, symbol: str, rs: RSResult,
                 liquidity: LiquidityResult, rr: RRResult, benchmark: str,
                 rs_window_min: int, spread_abs: float, spread_bps: float,
                 volume_context: dict, alt_targets: dict, killzone: str,
                 mode: str = "live", htf_trend: str | None = None) -> Signal:
    direction = candidate.direction
    rs_ok = rs.long_ok if direction == "long" else rs.short_ok
    trend_ok = (htf_trend is None
                or (direction == "long" and htf_trend == "up")
                or (direction == "short" and htf_trend == "down"))
    qualified = rs_ok and liquidity.ok and rr.rr_ok and trend_ok
    return Signal(
        signal_id=make_signal_id(symbol, candidate.level_type, candidate.reentry_ts),
        symbol=symbol, direction=direction, level_type=candidate.level_type,
        level_price=candidate.level_price, sweep_time=candidate.sweep_ts,
        reentry_time=candidate.reentry_ts, wick_extreme=candidate.wick_extreme,
        entry_price=rr.entry, stop_price=rr.stop, target_price=rr.target,
        alt_targets=alt_targets, risk=rr.risk, reward=rr.reward, rr=rr.rr,
        rs_score=rs.rs, rs_window_min=rs_window_min, benchmark=benchmark,
        spread_bps=spread_bps, spread_abs=spread_abs, volume_context=volume_context,
        htf_bias=htf_trend, killzone=killzone, mode=mode, qualified=qualified,
    )
