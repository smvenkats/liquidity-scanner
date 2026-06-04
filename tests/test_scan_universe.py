# tests/test_scan_universe.py
from datetime import datetime, timedelta
from execution.models import Bar
from execution.config import load_params
from execution.scanner.universe import is_inplay, select_inplay

P = load_params()

def _b(ts, o, h, l, c, v=80_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

def _liquid_daily():
    return [_b(datetime(2026, 6, 2), 100, 110, 99, 100),
            _b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100)]

def _gapped_session():   # opens 3% below prior close 100 -> gap in play
    s = datetime(2026, 6, 4, 13, 30)
    return [_b(s + timedelta(minutes=5 * i), 97, 97.2, 96.8, 97, v=500_000) for i in range(20)]

class Feed:
    def __init__(self, data): self._d = data
    def bars(self, sym, tf): return self._d.get((sym, tf), [])

def test_gapped_liquid_name_is_in_play():
    bars5 = _gapped_session()
    assert is_inplay(_liquid_daily(), bars5, P) is True

def test_cheap_name_excluded():
    cheap = [_b(datetime(2026, 6, 4, 13, 30) + timedelta(minutes=5 * i), 3, 3.1, 2.9, 3) for i in range(20)]
    assert is_inplay(_liquid_daily(), cheap, P) is False

def test_illiquid_name_excluded():
    thin_daily = [_b(datetime(2026, 6, 2), 100, 110, 99, 100, v=100_000),
                  _b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=100_000)]
    assert is_inplay(thin_daily, _gapped_session(), P) is False

def test_select_inplay_filters_and_caps():
    feed = Feed({("AAA", "1d"): _liquid_daily(), ("AAA", "5m"): _gapped_session(),
                 ("BBB", "1d"): _liquid_daily(),
                 ("BBB", "5m"): [_b(datetime(2026, 6, 4, 13, 30), 100, 100.1, 99.9, 100)]})
    picked = select_inplay(["AAA", "BBB"], feed, P)
    assert "AAA" in picked and "BBB" not in picked   # BBB neither gapped nor near a level
