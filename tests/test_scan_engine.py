# tests/test_scan_engine.py
from datetime import datetime, timedelta, date
from execution.models import Bar
from execution.config import load_params
from execution.scanner.engine import SymbolScanner, scan_once, proximity_state

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

class Feed:
    def __init__(self, data): self._d = data
    def bars(self, sym, tf): return self._d.get((sym, tf), [])

def _feed():
    s = datetime(2026, 6, 4, 13, 30)
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000),
             _b(datetime(2026, 6, 4), 100, 111, 98, 110, v=80_000_000)]
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    sess = [_b(s, 99.20, 99.40, 99.10, 99.30),
            _b(s + timedelta(minutes=5), 99.30, 99.50, 99.20, 99.40),
            _b(s + timedelta(minutes=10), 99.40, 99.60, 99.30, 99.50),
            _b(s + timedelta(minutes=15), 99.50, 99.70, 99.40, 99.60),
            _b(s + timedelta(minutes=20), 99.60, 99.80, 98.50, 99.70, v=2_000_000)]
    sym5 = warm + sess
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in sym5]
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    return Feed({("ABC", "5m"): sym5, ("ABC", "1d"): daily, ("ABC", "1h"): h1,
                 ("SPY", "5m"): bench5})

def test_emits_qualified_signal_once_then_dedups():
    feed, P = _feed(), load_params()
    states = {}
    first = scan_once(["ABC"], feed, states, P, benchmark="SPY")
    assert len(first) == 1 and first[0].symbol == "ABC" and first[0].qualified
    second = scan_once(["ABC"], feed, states, P, benchmark="SPY")   # same bars
    assert second == []                                             # already emitted

def test_proximity_state_reports_watching_near_level():
    P = load_params()
    # price 99.05 within 0.5*atr of PDL 99.0
    assert proximity_state(99.05, levels_pdh=110.0, levels_pdl=99.0, atr5=1.0, params=P) == "WATCHING"
    assert proximity_state(105.0, levels_pdh=110.0, levels_pdl=99.0, atr5=1.0, params=P) == "IDLE"

def test_scan_once_skips_stale_feed_when_as_of_date_given():
    feed, P = _feed(), load_params()
    out = scan_once(["ABC"], feed, {}, P, benchmark="SPY", as_of_date=date(2026, 6, 5))
    assert out == []   # feed's latest session is 2026-06-04 -> skipped as stale

def test_scan_once_ignores_premarket_sweeps():
    feed, P = _feed(), load_params()
    base = datetime(2026, 6, 4, 13, 0)  # 09:00 ET, before regular session
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000),
             _b(datetime(2026, 6, 4), 100, 111, 98, 110, v=80_000_000)]
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    premarket = [_b(base, 99.20, 99.40, 98.50, 99.70, v=2_000_000)]
    sym5 = warm + premarket
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in sym5]
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    f = Feed({("ABC", "5m"): sym5, ("ABC", "1d"): daily, ("ABC", "1h"): h1, ("SPY", "5m"): bench5})

    assert scan_once(["ABC"], f, {}, P, benchmark="SPY") == []
