from execution.config import load_params

def test_backtest_group_present():
    p = load_params()
    assert p["backtest"]["benchmark"] == "SPY"
    assert p["backtest"]["bars_per_rt_day"] == 78
