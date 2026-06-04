from datetime import datetime, timedelta
from execution.models import Bar
from execution.backtest.simulate import simulate_trade

def _bar(i, o, h, l, c):
    return Bar(ts=datetime(2026, 6, 4, 14, 0) + timedelta(minutes=5 * i),
               o=o, h=h, l=l, c=c, v=100)

BASE = dict(direction="long", level_type="PDL", symbol="ABC",
            entry_time=datetime(2026, 6, 4, 13, 0), entry_price=100.0,
            stop=99.0, target=102.0, killzone="ny_open", rs_score=0.4)

def test_target_hit_returns_positive_r():
    fwd = [_bar(0, 100.1, 100.5, 100.0, 100.4), _bar(1, 100.4, 102.1, 100.3, 101.9)]
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "target" and t.bars_held == 2
    assert round(t.r_multiple, 2) == 2.0    # reward 2.0 / risk 1.0

def test_stop_hit_returns_minus_one_r():
    fwd = [_bar(0, 100.0, 100.2, 98.9, 99.5)]
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "stop" and round(t.r_multiple, 2) == -1.0

def test_straddle_resolves_stop_first():
    fwd = [_bar(0, 100.0, 102.5, 98.5, 101.0)]   # bar hits BOTH stop and target
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "stop" and round(t.r_multiple, 2) == -1.0

def test_timeout_marks_partial_r_at_last_close():
    fwd = [_bar(0, 100.0, 100.6, 99.8, 100.5)]   # neither hit
    t = simulate_trade(forward_bars=fwd, **BASE)
    assert t.exit_reason == "timeout" and round(t.r_multiple, 2) == 0.5   # +0.5/1.0

def test_short_target_hit():
    short = {**BASE, "direction": "short", "stop": 101.0, "target": 98.0}
    fwd = [_bar(0, 100.0, 100.2, 97.9, 98.1)]
    t = simulate_trade(forward_bars=fwd, **short)
    assert t.exit_reason == "target" and round(t.r_multiple, 2) == 2.0
