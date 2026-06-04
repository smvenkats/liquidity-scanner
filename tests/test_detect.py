# tests/test_detect.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.detect import penetration_min, detect_bullish_sweep, detect_bearish_sweep

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

PEN = 0.05  # pen_min for these tests

def test_penetration_min_uses_max_of_floor_and_atr_fraction():
    assert penetration_min(atr5=2.0, pen_atr_frac=0.10, min_pen_abs=0.03) == 0.20
    assert penetration_min(atr5=0.1, pen_atr_frac=0.10, min_pen_abs=0.03) == 0.03

def test_bullish_sweep_detected_same_or_next_bar():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5),      # near level
            _bar(1, 100.3, 100.35, 99.80, 100.20)]    # wick to 99.80 (below 99.95), closes 100.20 > level
    c = detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1)
    assert c is not None
    assert c.direction == "long" and c.level_type == "PDL"
    assert c.wick_extreme == 99.80 and c.reentry_index == 1
    assert c.reentry_close == 100.20

def test_no_signal_when_wick_does_not_clear_pen_min():
    level = 100.0
    bars = [_bar(0, 100.1, 100.2, 99.97, 100.05)]  # low 99.97, only 0.03 below < PEN
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_no_signal_when_close_stays_below_level():
    level = 100.0
    bars = [_bar(0, 100.1, 100.2, 99.80, 99.90)]  # swept but close 99.90 < level
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_late_reentry_rejected_when_max_reentry_bars_is_one():
    level = 100.0
    # bar 0 is the only sweep; bars 1 and 2 must NOT themselves pierce (low >= level-PEN=99.95),
    # so the reclaim at bar 2 is out of bar 0's 1-bar window and attributable to no in-window sweep.
    bars = [_bar(0, 100.1, 100.20, 99.80, 99.90),    # sweep at bar 0, closes below
            _bar(1, 99.97, 99.99, 99.96, 99.97),     # not a sweep, still below level
            _bar(2, 100.0, 100.30, 99.96, 100.20)]   # reclaims above but is not itself a sweep
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1) is None

def test_sustained_volume_confirms_on_high_window_volume():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(1, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(2, 100.3, 100.35, 99.80, 99.90, v=300),   # sweep, close below
            _bar(3, 99.9, 100.30, 99.85, 100.20, v=500)]   # reentry on high volume
    c = detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1,
                             confirm_vol=True, sustained_window_bars=2,
                             sustained_baseline_bars=2, sustained_mult=1.75)
    # window vol = 300+500=800 ; baseline = avg(100,100)*2 = 200 ; 800 >= 1.75*200 -> ok
    assert c is not None and c.reentry_index == 3

def test_sustained_volume_blocks_on_low_window_volume():
    level = 100.0
    bars = [_bar(0, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(1, 100.5, 100.6, 100.4, 100.5, v=100),
            _bar(2, 100.3, 100.35, 99.80, 99.90, v=100),
            _bar(3, 99.9, 100.30, 99.85, 100.20, v=100)]   # reentry on flat volume
    # window vol = 200 ; baseline = 200 ; 200 >= 1.75*200 is False -> suppressed
    assert detect_bullish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1,
                                confirm_vol=True, sustained_window_bars=2,
                                sustained_baseline_bars=2, sustained_mult=1.75) is None

def test_bearish_sweep_detected():
    level = 200.0
    bars = [_bar(0, 199.7, 200.40, 199.6, 199.80)]  # wick to 200.40 (>200.05), closes 199.80 < level
    c = detect_bearish_sweep(bars, level, pen_min=PEN, max_reentry_bars=1)
    assert c is not None and c.direction == "short" and c.level_type == "PDH"
    assert c.wick_extreme == 200.40
