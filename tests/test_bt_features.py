from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from execution.models import Bar
from execution.backtest.features import (
    adv_from_daily, modeled_spread, rvol_from_adv, killzone, close_now_prev,
    is_rth, market_date)

def _b(ts, c, v=100):
    return Bar(ts=ts, o=c, h=c, l=c, c=c, v=v)

def test_adv_from_daily_averages_recent_volume():
    days = [_b(datetime(2026, 6, d), 100, v=vol) for d, vol in [(1, 10), (2, 20), (3, 30)]]
    assert adv_from_daily(days, lookback=2) == 25.0   # mean of last two

def test_modeled_spread_steps_with_liquidity():
    assert modeled_spread(100.0, 6_000_000) == 0.01    # 1 bp -> 0.01, floored
    assert modeled_spread(500.0, 2_000_000) == round(500 * 3 / 10_000, 2)   # 3 bps
    assert modeled_spread(50.0, 500_000) == round(50 * 8 / 10_000, 2)       # 8 bps

def test_rvol_from_adv_uses_per_bar_average():
    # adv 78000 -> avg 5m vol 1000 ; a 1500-vol bar -> rvol 1.5
    assert rvol_from_adv(1500, 78_000) == 1.5
    assert rvol_from_adv(1500, 0) == 0.0

def test_killzone_buckets_by_eastern_time():
    open_utc = datetime(2026, 6, 4, 13, 35)   # 09:35 ET
    power_utc = datetime(2026, 6, 4, 18, 30)  # 14:30 ET
    mid_utc = datetime(2026, 6, 4, 16, 30)    # 12:30 ET
    assert killzone(open_utc) == "ny_open"
    assert killzone(power_utc) == "power_hour"
    assert killzone(mid_utc) == "midday"

def test_killzone_respects_timezone_aware_exchange_time():
    et = ZoneInfo("America/New_York")
    assert killzone(datetime(2026, 6, 18, 9, 50, tzinfo=et)) == "ny_open"
    assert killzone(datetime(2026, 6, 18, 9, 25, tzinfo=et)) == "pre_rth"
    assert is_rth(datetime(2026, 6, 18, 9, 30, tzinfo=et))
    assert not is_rth(datetime(2026, 6, 18, 9, 25, tzinfo=et))
    assert market_date(datetime(2026, 6, 18, 23, 0, tzinfo=et)).isoformat() == "2026-06-18"

def test_close_now_prev_returns_now_and_lagged_close():
    base = datetime(2026, 6, 4, 14, 0)
    bars = [_b(base + timedelta(minutes=5 * i), 100 + i) for i in range(6)]
    now_prev = close_now_prev(bars, base + timedelta(minutes=25), 20)  # now idx5; 20min back -> idx1
    assert now_prev == (105.0, 101.0)
    assert close_now_prev(bars, base, 20) is None   # no bar 20 min before base
