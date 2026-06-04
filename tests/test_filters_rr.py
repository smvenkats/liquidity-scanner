# tests/test_filters_rr.py
from execution.filters import risk_reward

def test_long_rr_with_wick_stop():
    # entry 100.20, wick_extreme 99.80, buffer=max(0.02, 0.05*atr, spread)
    r = risk_reward(direction="long", entry=100.20, wick_extreme=99.80, target=102.00,
                    atr5=1.0, current_spread=0.03, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer = max(0.02, 0.05, 0.03) = 0.05 -> stop 99.75 ; risk 0.45 ; reward 1.80 ; rr 4.0
    assert r.buffer == 0.05 and round(r.stop, 2) == 99.75
    assert round(r.risk, 2) == 0.45 and round(r.reward, 2) == 1.80
    assert round(r.rr, 2) == 4.0 and r.rr_ok is True

def test_short_rr_with_wick_stop():
    r = risk_reward(direction="short", entry=199.80, wick_extreme=200.40, target=198.00,
                    atr5=1.0, current_spread=0.02, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer=max(0.02,0.05,0.02)=0.05 -> stop 200.45 ; risk 0.65 ; reward 1.80 ; rr ~2.77
    assert round(r.stop, 2) == 200.45 and r.rr_ok is True

def test_rr_below_threshold_fails():
    r = risk_reward(direction="long", entry=100.20, wick_extreme=99.80, target=100.80,
                    atr5=1.0, current_spread=0.03, buf_abs=0.02, buf_atr_frac=0.05,
                    min_rr=2.0)
    # buffer 0.05, risk 0.45, reward 0.60, rr ~1.33 < 2
    assert r.rr_ok is False
