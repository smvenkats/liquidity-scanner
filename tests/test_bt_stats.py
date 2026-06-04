from execution.backtest.stats import summarize, slice_by

class T:   # lightweight trade stand-in (summarize only reads r_multiple/bars_held/killzone)
    def __init__(self, r, held=1, kz="ny_open"):
        self.r_multiple, self.bars_held, self.killzone = r, held, kz

def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0 and s["win_rate"] == 0.0 and s["expectancy_r"] == 0.0

def test_summarize_basic_metrics():
    trades = [T(2.0), T(2.0), T(-1.0), T(-1.0)]   # 2 wins +2R, 2 losses -1R
    s = summarize(trades)
    assert s["n"] == 4 and s["win_rate"] == 0.5
    assert round(s["expectancy_r"], 2) == 0.5            # (2+2-1-1)/4
    assert round(s["profit_factor"], 2) == 2.0           # 4 / 2

def test_profit_factor_infinite_when_no_losses():
    assert summarize([T(2.0), T(1.0)])["profit_factor"] == float("inf")

def test_slice_by_groups_and_summarizes():
    trades = [T(2.0, kz="ny_open"), T(-1.0, kz="ny_open"), T(2.0, kz="midday")]
    by = slice_by(trades, lambda t: t.killzone)
    assert by["ny_open"]["n"] == 2 and by["midday"]["n"] == 1
    assert by["midday"]["win_rate"] == 1.0
