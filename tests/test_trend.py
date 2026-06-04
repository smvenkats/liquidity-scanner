# tests/test_trend.py
from execution.trend import ema, htf_trend

def test_ema_seeds_with_sma_then_updates():
    # length 3: seed = mean(10,11,12)=11 ; k=0.5 ; e = 13*0.5 + 11*0.5 = 12
    assert ema([10, 11, 12, 13], 3) == 12.0

def test_trend_up_when_last_close_above_ema():
    assert htf_trend([10, 10, 10, 10, 20], ema_len=3) == "up"

def test_trend_down_when_last_close_below_ema():
    assert htf_trend([20, 20, 20, 20, 5], ema_len=3) == "down"

def test_trend_flat_when_insufficient_history():
    assert htf_trend([10, 11], ema_len=5) == "flat"

def test_require_slope_rejects_when_ema_not_rising():
    # downtrend with a small last bounce: not a valid 'up'
    assert htf_trend([30, 20, 15, 12, 13], ema_len=3, require_slope=True) in ("flat", "down")

def test_require_slope_confirms_up_when_ema_rising():
    # steadily rising closes -> ema rising and last above ema -> 'up'
    assert htf_trend([10, 11, 12, 13, 14], ema_len=3, require_slope=True) == "up"
