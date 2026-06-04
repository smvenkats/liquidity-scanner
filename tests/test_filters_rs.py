# tests/test_filters_rs.py
from execution.filters import relative_strength

# rs_thresh/bench_flat_max are FRACTIONS (0.30% -> 0.003, 0.20% -> 0.002)
def test_long_ok_when_outperforms_and_bench_flat():
    r = relative_strength(sym_now=101.0, sym_prev=100.0,   # +1.0%
                          bench_now=100.1, bench_prev=100.0, # +0.1%
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert round(r.rs, 5) == 0.009
    assert r.long_ok is True and r.short_ok is False

def test_long_blocked_when_bench_too_strong():
    r = relative_strength(sym_now=101.0, sym_prev=100.0,
                          bench_now=100.5, bench_prev=100.0,  # +0.5% > flat band
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert r.long_ok is False

def test_short_ok_when_underperforms_and_bench_firm():
    r = relative_strength(sym_now=99.0, sym_prev=100.0,      # -1.0%
                          bench_now=99.9, bench_prev=100.0,   # -0.1%
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert r.short_ok is True and r.long_ok is False

def test_zero_prior_price_disqualifies_without_crashing():
    r = relative_strength(sym_now=10.0, sym_prev=0.0, bench_now=100.0, bench_prev=100.0,
                          rs_thresh=0.003, bench_flat_max=0.002)
    assert r.long_ok is False and r.short_ok is False and r.rs == 0.0
