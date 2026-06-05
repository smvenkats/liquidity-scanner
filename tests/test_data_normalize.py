import pytest
from execution.data.normalize import from_questrade_candle, from_yf_record

def test_from_questrade_candle_maps_fields():
    c = {"start": "2024-01-02T09:30:00.000000-05:00", "open": "1.5",
         "high": 2, "low": 1, "close": 1.75, "volume": 1000}
    assert from_questrade_candle(c) == {
        "ts": "2024-01-02T09:30:00.000000-05:00",
        "o": 1.5, "h": 2.0, "l": 1.0, "c": 1.75, "v": 1000.0,
    }

def test_from_questrade_candle_missing_field_raises():
    with pytest.raises(KeyError):
        from_questrade_candle({"start": "x", "open": 1, "high": 2, "low": 1, "close": 1})

def test_from_yf_record_maps_fields():
    rec = {"ts": "2024-01-02T10:00:00-05:00", "Open": "1", "High": 2.0,
           "Low": 0.5, "Close": 1.5, "Volume": "50"}
    assert from_yf_record(rec) == {
        "ts": "2024-01-02T10:00:00-05:00",
        "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 50.0,
    }

def test_from_yf_record_missing_field_raises():
    with pytest.raises(KeyError):
        from_yf_record({"ts": "x", "Open": 1, "High": 2, "Low": 0.5, "Close": 1.5})
