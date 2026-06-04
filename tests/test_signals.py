# tests/test_signals.py
from datetime import datetime
from execution.detect import SweepCandidate
from execution.filters import RSResult, LiquidityResult, RRResult
from execution.signals import make_signal_id, build_signal

def _candidate():
    ts_sweep = datetime.fromisoformat("2026-06-04T14:30:00-04:00")
    ts_re = datetime.fromisoformat("2026-06-04T14:35:00-04:00")
    return SweepCandidate(direction="long", level_type="PDL", level_price=187.40,
                          sweep_index=0, sweep_ts=ts_sweep, reentry_index=1,
                          reentry_ts=ts_re, wick_extreme=187.05, reentry_close=187.55,
                          reentry_volume=2_000_000)

def test_make_signal_id_format():
    ts = datetime.fromisoformat("2026-06-04T14:35:00-04:00")
    assert make_signal_id("AAPL", "PDL", ts) == "AAPL-PDL-20260604T1435"

def test_build_signal_qualified_when_all_pass():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=190.10, buffer=0.07,
                  risk=0.57, reward=2.55, rr=4.47, rr_ok=True)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={"vwap": 188.30},
                       killzone="ny_open", mode="live", htf_trend="up")
    assert sig.qualified is True and sig.direction == "long"
    d = sig.to_dict()
    assert d["entry_price"] == 187.55 and d["sweep_time"] == "2026-06-04T14:30:00-04:00"
    assert d["rr"] == 4.47 and d["qualified"] is True and d["htf_bias"] == "up"

def test_build_signal_blocked_when_1h_trend_opposes():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=190.10, buffer=0.07,
                  risk=0.57, reward=2.55, rr=4.47, rr_ok=True)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={}, killzone="ny_open",
                       htf_trend="down")   # long setup but 1h trend down -> blocked
    assert sig.qualified is False

def test_build_signal_not_qualified_when_rr_fails():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=188.00, buffer=0.07,
                  risk=0.57, reward=0.45, rr=0.79, rr_ok=False)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={}, killzone="ny_open")
    assert sig.qualified is False

def test_build_signal_blocked_when_1h_trend_flat():
    rs = RSResult(rs=0.0041, ret_sym=0.005, ret_bench=0.0009, long_ok=True, short_ok=False)
    liq = LiquidityResult(ok=True, checks={})
    rr = RRResult(entry=187.55, stop=186.98, target=190.10, buffer=0.07,
                  risk=0.57, reward=2.55, rr=4.47, rr_ok=True)
    sig = build_signal(candidate=_candidate(), symbol="AAPL", rs=rs, liquidity=liq, rr=rr,
                       benchmark="QQQ", rs_window_min=20, spread_abs=0.03, spread_bps=4.2,
                       volume_context={"rvol": 1.8}, alt_targets={}, killzone="ny_open",
                       htf_trend="flat")
    assert sig.qualified is False
