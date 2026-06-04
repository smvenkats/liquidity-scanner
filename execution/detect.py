# execution/detect.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from execution.models import Bar


@dataclass(frozen=True)
class SweepCandidate:
    direction: str          # "long" | "short"
    level_type: str         # "PDL" | "PDH"
    level_price: float
    sweep_index: int
    sweep_ts: datetime
    reentry_index: int
    reentry_ts: datetime
    wick_extreme: float
    reentry_close: float


def penetration_min(atr5: float, pen_atr_frac: float, min_pen_abs: float) -> float:
    return max(min_pen_abs, pen_atr_frac * atr5)


def sustained_volume_ok(bars: list[Bar], end_index: int, *, window: int,
                        baseline_bars: int, mult: float) -> bool:
    """~15-min sustained-volume confirmation on the 5m grid, lookahead-safe.

    Compares the summed volume of the `window` completed bars ending at end_index
    against `mult` x the trailing per-bar average over the `baseline_bars` bars
    immediately before that window. Uses only bars up to end_index (no peeking at an
    unclosed higher-timeframe bar). Insufficient warmup -> cannot confirm -> suppress.
    """
    if end_index + 1 < window + baseline_bars:
        return False
    win = bars[end_index - window + 1: end_index + 1]
    base = bars[end_index - window - baseline_bars + 1: end_index - window + 1]
    vol_window = sum(b.v for b in win)
    avg_bar = sum(b.v for b in base) / baseline_bars
    baseline = avg_bar * window
    return baseline > 0 and vol_window >= mult * baseline


def _scan(bars: list[Bar], level_price: float, side: str, *, pen_min: float,
          max_reentry_bars: int, confirm_vol: bool = False,
          sustained_window_bars: int = 3, sustained_baseline_bars: int = 20,
          sustained_mult: float = 1.75) -> SweepCandidate | None:
    n = len(bars)
    for i in range(n):
        breached = (bars[i].l < level_price - pen_min) if side == "long" \
            else (bars[i].h > level_price + pen_min)
        if not breached:
            continue
        last_j = min(i + max_reentry_bars, n - 1)
        for j in range(i, last_j + 1):
            window = bars[i:j + 1]
            if side == "long":
                wick = min(b.l for b in window)
                reentry = bars[j].c > level_price and wick < level_price - pen_min
            else:
                wick = max(b.h for b in window)
                reentry = bars[j].c < level_price and wick > level_price + pen_min
            if not reentry:
                continue
            if confirm_vol and not sustained_volume_ok(
                    bars, j, window=sustained_window_bars,
                    baseline_bars=sustained_baseline_bars, mult=sustained_mult):
                continue
            return SweepCandidate(
                direction=side,
                level_type="PDL" if side == "long" else "PDH",
                level_price=level_price,
                sweep_index=i, sweep_ts=bars[i].ts,
                reentry_index=j, reentry_ts=bars[j].ts,
                wick_extreme=wick, reentry_close=bars[j].c,
            )
    return None


def detect_bullish_sweep(bars, level_price, **kw) -> SweepCandidate | None:
    return _scan(bars, level_price, "long", **kw)


def detect_bearish_sweep(bars, level_price, **kw) -> SweepCandidate | None:
    return _scan(bars, level_price, "short", **kw)
