# tests/test_pipeline.py
from datetime import datetime, timedelta
from execution.models import Bar, Level
from execution.detect import detect_bullish_sweep, penetration_min
from execution.indicators import atr
from execution.pipeline import ScanContext, qualify_candidate

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

def _ctx(trend_gate=True):
    s = datetime(2026, 6, 4, 13, 30)
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    sess = [_b(s, 99.20, 99.40, 99.10, 99.30),
            _b(s + timedelta(minutes=5), 99.30, 99.50, 99.20, 99.40),
            _b(s + timedelta(minutes=10), 99.40, 99.60, 99.30, 99.50),
            _b(s + timedelta(minutes=15), 99.50, 99.70, 99.40, 99.60),
            _b(s + timedelta(minutes=20), 99.60, 99.80, 98.50, 99.70, v=2_000_000)]
    bars5 = warm + sess
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in bars5]
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000)]
    from execution.config import load_params
    p = load_params()
    atr5 = atr(warm, p["detection"]["atr_len"])
    return ScanContext(symbol="ABC", bars5=bars5, bench5=bench5, h1=h1,
                       adv=80_000_000, atr5=atr5, levels=Level(110.0, 99.0, None),
                       params=p, benchmark="SPY", trend_gate=trend_gate, mode="live"), sess, atr5, p

def test_qualifies_a_clean_long_sweep():
    ctx, sess, atr5, p = _ctx(trend_gate=True)
    pen = penetration_min(atr5, p["detection"]["pen_atr_frac"], p["detection"]["min_pen_abs"])
    c = detect_bullish_sweep(sess, ctx.levels.pdl, pen_min=pen,
                             max_reentry_bars=p["detection"]["max_reentry_bars"])
    sig = qualify_candidate(c, ctx)
    assert sig.qualified is True and sig.direction == "long"
    assert sig.target_price == 110.0 and sig.htf_bias == "up"

def test_trend_gate_off_changes_nothing_for_aligned_trend():
    ctx, sess, atr5, p = _ctx(trend_gate=False)
    pen = penetration_min(atr5, p["detection"]["pen_atr_frac"], p["detection"]["min_pen_abs"])
    c = detect_bullish_sweep(sess, ctx.levels.pdl, pen_min=pen,
                             max_reentry_bars=p["detection"]["max_reentry_bars"])
    sig = qualify_candidate(c, ctx)
    assert sig.qualified is True and sig.htf_bias is None   # gate off -> no trend stored

def test_qualify_reads_candidate_reentry_volume():
    from dataclasses import replace
    from execution.detect import detect_bullish_sweep, penetration_min
    ctx, sess, atr5, p = _ctx(trend_gate=True)
    pen = penetration_min(atr5, p["detection"]["pen_atr_frac"], p["detection"]["min_pen_abs"])
    c = detect_bullish_sweep(sess, ctx.levels.pdl, pen_min=pen,
                             max_reentry_bars=p["detection"]["max_reentry_bars"])
    low = replace(c, reentry_volume=1000)          # tiny -> rvol << 1.0 fails liquidity
    assert qualify_candidate(low, ctx).qualified is False
