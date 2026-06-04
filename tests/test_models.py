# tests/test_models.py
from datetime import datetime
from execution.models import Bar, Quote, Level

def test_bar_from_questrade_parses_iso_ts_and_floats():
    d = {"ts": "2026-06-04T16:20:00+00:00", "o": 756.38, "h": 756.67,
         "l": 756.30, "c": 756.61, "v": 526232}
    b = Bar.from_questrade(d)
    assert isinstance(b.ts, datetime)
    assert b.ts.hour == 16 and b.h == 756.67 and b.v == 526232.0

def test_quote_spread_and_mid():
    q = Quote(bid=10.00, ask=10.04, bid_size=1500, ask_size=1200)
    assert round(q.spread, 4) == 0.04
    assert q.mid == 10.02
