# tests/test_filters_liquidity.py
from execution.filters import liquidity_ok

BASE = dict(
    adv_20d=50_000_000, bar_volume=20_000, bar_close=200.0, rvol=1.8,
    bid=199.98, ask=200.02, bid_size=1500, ask_size=1400, risk=0.50,
    min_adv_shares=1_000_000, min_bar_dollar_vol=1_000_000, min_rvol=1.0,
    max_spread_abs=0.05, max_spread_pct=0.0008, min_book_shares=2000,
    spread_risk_frac=0.33,
)

def test_all_checks_pass():
    r = liquidity_ok(**BASE)
    assert r.ok is True
    assert all(r.checks.values())

def test_spread_vs_risk_blocks_tight_stop():
    bad = {**BASE, "risk": 0.10}  # spread 0.04 > 0.33*0.10=0.033
    r = liquidity_ok(**bad)
    assert r.ok is False and r.checks["spread_vs_risk"] is False

def test_low_rvol_blocks():
    r = liquidity_ok(**{**BASE, "rvol": 0.5})
    assert r.ok is False and r.checks["rvol"] is False

def test_optional_book_size_skipped_when_none():
    r = liquidity_ok(**{**BASE, "min_book_shares": None})
    assert r.checks["book"] is True
