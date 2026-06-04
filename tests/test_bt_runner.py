from datetime import datetime, timedelta
from execution.models import Bar
from execution.backtest.runner import run_backtest, gate_lift

def _b(ts, o, h, l, c, v=1_000_000):
    return Bar(ts=ts, o=o, h=h, l=l, c=c, v=v)

class StubStore:
    """In-memory store so the runner test needs no files."""
    def __init__(self, data, sessions):
        self._data, self._sessions = data, sessions
    def bars(self, symbol, tf):
        return self._data.get((symbol, tf), [])
    def sessions(self, symbol):
        return self._sessions

def _make_store():
    from datetime import date
    d = date(2026, 6, 4)
    s = datetime(2026, 6, 4, 13, 30)   # 09:30 ET (ny_open killzone)
    # prior day (06-03) daily bar -> PDL=99.0, PDH=110.0
    daily = [_b(datetime(2026, 6, 3), 100, 110.0, 99.0, 100, v=80_000_000),
             _b(datetime(2026, 6, 4), 100, 111, 98, 110, v=80_000_000)]
    # 20 warmup 5m bars (prior session) ~99.3 with small range -> ATR context
    warm = [_b(datetime(2026, 6, 3, 19, 0) + timedelta(minutes=5 * i),
               99.30, 99.45, 99.15, 99.30) for i in range(20)]
    # session: build above PDL, then dip-sweep PDL with same-bar reclaim (high vol), run to PDH
    sess = [
        _b(s,                          99.20, 99.40, 99.10, 99.30),
        _b(s + timedelta(minutes=5),   99.30, 99.50, 99.20, 99.40),
        _b(s + timedelta(minutes=10),  99.40, 99.60, 99.30, 99.50),
        _b(s + timedelta(minutes=15),  99.50, 99.70, 99.40, 99.60),
        _b(s + timedelta(minutes=20),  99.60, 99.80, 98.50, 99.70, v=2_000_000),  # sweep+reclaim
        _b(s + timedelta(minutes=25),  99.70, 100.50, 99.60, 100.40),
        _b(s + timedelta(minutes=30),  100.40, 103.00, 100.30, 102.50),
        _b(s + timedelta(minutes=35),  102.50, 110.50, 102.40, 110.20),   # hits PDH 110 target
    ]
    sym5 = warm + sess
    # benchmark (SPY) flat -> the symbol (up 0.4% over the 20-min window) shows relative strength
    bench5 = [_b(b.ts, 500, 500, 500, 500, v=1) for b in sym5]
    # 1h closes steadily rising -> last completed 1h above its EMA -> trend 'up' (long allowed)
    h1 = [_b(datetime(2026, 6, 3, 13, 30) + timedelta(hours=i), 90 + i, 90 + i, 90 + i, 90 + i)
          for i in range(25)]
    data = {("ABC", "5m"): sym5, ("ABC", "1d"): daily, ("ABC", "1h"): h1,
            ("SPY", "5m"): bench5}
    return StubStore(data, [d])

def test_run_backtest_produces_a_winning_trade():
    store = _make_store()
    res = run_backtest(["ABC"], store, benchmark="SPY", trend_gate=True)
    assert res["overall"]["n"] >= 1
    # the crafted long sweep should reach the PDH target
    assert any(t.exit_reason == "target" for t in res["trades"])
    assert "by_killzone" in res and "by_level" in res

def test_gate_lift_returns_on_off_comparison():
    store = _make_store()
    lift = gate_lift(["ABC"], store, benchmark="SPY")
    assert "gate_on" in lift and "gate_off" in lift
    assert lift["gate_off"]["n"] >= lift["gate_on"]["n"]   # OFF never filters fewer
