from datetime import datetime, timedelta
from execution.models import Bar
from execution.detect import detect_bullish_sweep
from execution.backtest.replay import find_all_sweeps

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

def test_finds_multiple_sweeps_of_same_level():
    level = 100.0
    bars = [_bar(0, 100.3, 100.35, 99.80, 100.20),   # sweep #1 (same-bar reclaim)
            _bar(1, 100.2, 100.30, 100.10, 100.25),  # away from level
            _bar(2, 100.2, 100.30, 99.78, 100.21)]   # sweep #2 (same-bar reclaim)
    out = find_all_sweeps(bars, level, detect_bullish_sweep, pen_min=0.05, max_reentry_bars=1)
    assert len(out) == 2
    assert out[0].reentry_index == 0 and out[1].reentry_index == 2
    assert out[0].sweep_ts < out[1].sweep_ts

def test_returns_empty_when_no_sweep():
    bars = [_bar(0, 101, 101.2, 100.9, 101.1)]
    assert find_all_sweeps(bars, 100.0, detect_bullish_sweep, pen_min=0.05, max_reentry_bars=1) == []
