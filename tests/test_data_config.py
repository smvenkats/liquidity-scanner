from execution.config import load_params

def test_data_block_present_and_shaped():
    p = load_params()
    d = p["data"]
    assert d["out_dir"] == "data/bars"
    assert d["benchmark"] == "SPY"
    assert "QQQ" in d["universe"] and len(d["universe"]) >= 8
    assert d["timeframes"] == ["5m", "1h", "1d"]
    assert d["lookback_years"] == 2
    assert d["windows"]["5m"]["interval"] == "FiveMinutes"
    assert d["windows"]["5m"]["window_days"] == 2
    assert d["windows"]["5m"]["max_lookback_days"] == 100   # Questrade intraday horizon cap
    assert d["windows"]["1h"]["window_days"] == 25
    assert d["windows"]["1d"]["window_days"] == 400
