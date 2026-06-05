import pytest
from datetime import datetime, timezone
from execution.data import yfinance_client as yfc


def test_fetch_rejects_5m():
    with pytest.raises(ValueError):
        yfc.fetch("SPY", "5m", datetime(2024, 1, 1, tzinfo=timezone.utc),
                  datetime(2024, 1, 2, tzinfo=timezone.utc))


def test_fetch_normalizes_and_passes_interval(monkeypatch):
    captured = {}

    def fake_dl(symbol, start, end, interval):
        captured.update(symbol=symbol, interval=interval, start=start, end=end)
        return [{"ts": "2024-01-02T10:00:00-05:00", "Open": 1, "High": 2,
                 "Low": 0.5, "Close": 1.5, "Volume": 9}]

    monkeypatch.setattr(yfc, "_raw_download", fake_dl)
    rows = yfc.fetch("SPY", "1h", datetime(2024, 1, 1, tzinfo=timezone.utc),
                     datetime(2024, 1, 3, tzinfo=timezone.utc))
    assert rows == [{"ts": "2024-01-02T10:00:00-05:00", "o": 1.0, "h": 2.0,
                     "l": 0.5, "c": 1.5, "v": 9.0}]
    assert captured["interval"] == "60m"


def test_fetch_clamps_1h_to_730_days(monkeypatch):
    captured = {}
    monkeypatch.setattr(yfc, "_raw_download",
                        lambda symbol, start, end, interval: captured.update(start=start) or [])
    end = datetime(2024, 6, 1, tzinfo=timezone.utc)
    far_start = datetime(2020, 1, 1, tzinfo=timezone.utc)  # ~1600 days back
    yfc.fetch("SPY", "1h", far_start, end)
    assert (end - captured["start"]).days <= 730
