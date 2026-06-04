# tests/test_config.py
from execution.config import load_params

def test_defaults_match_spec():
    p = load_params()
    assert p["rs"]["rs_thresh"] == 0.003          # 0.30% as a fraction
    assert p["rs"]["bench_flat_max"] == 0.002
    assert p["rr"]["min_rr"] == 2.0
    assert p["detection"]["max_reentry_bars"] == 1
    assert p["detection"]["confirm_vol"] is False
    assert p["detection"]["sustained_mult"] == 1.75
    assert p["liquidity"]["max_spread_pct"] == 0.0008
    assert p["policy"]["rearm"] == "every_sweep"
    assert p["trend"]["htf_trend_gate"] is True
    assert p["trend"]["htf_ema_len"] == 20
