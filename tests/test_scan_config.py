# tests/test_scan_config.py
from execution.config import load_params

def test_universe_inplay_thresholds_present():
    u = load_params()["universe"]
    assert u["min_price"] == 5.0
    assert u["min_adv_shares"] == 1_000_000
    assert u["gap_pct"] == 0.01
    assert u["near_level_atr"] == 0.5
