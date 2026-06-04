# tests/test_indicators.py
from datetime import datetime, timedelta
import pytest
from execution.models import Bar
from execution.indicators import atr, rvol, session_vwap

def _bar(i, o, h, l, c, v=100):
    return Bar(ts=datetime(2026, 6, 4) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=v)

def test_atr_simple_mean_of_true_range():
    # 3 bars, length=2. prev close chains: TR2=max(12-8,|12-10|,|8-10|)=4 ; TR3=max(11-9,|11-9|,|9-9|)=2
    bars = [_bar(0, 10, 10, 10, 10), _bar(1, 10, 12, 8, 9), _bar(2, 9, 11, 9, 9)]
    assert atr(bars, 2) == 3.0

def test_atr_needs_length_plus_one_bars():
    bars = [_bar(0, 10, 10, 10, 10), _bar(1, 10, 12, 8, 9)]
    with pytest.raises(ValueError):
        atr(bars, 2)

def test_rvol_ratio_and_zero_guard():
    assert rvol(150, 100) == 1.5
    assert rvol(150, 0) == 0.0

def test_session_vwap_typical_price_weighted():
    # one bar typical=(12+8+10)/3=10, vol=100 -> vwap=10
    bars = [_bar(0, 9, 12, 8, 10, v=100)]
    assert session_vwap(bars) == 10.0
