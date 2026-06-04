import json
from datetime import date
from execution.models import Bar
from execution.backtest.store import BarStore

def _write(tmp_path, name, rows):
    (tmp_path / name).write_text(json.dumps(rows))

def test_loads_bars_and_lists_sessions(tmp_path):
    _write(tmp_path, "ABC_5m.json", [
        {"ts": "2026-06-03T19:55:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        {"ts": "2026-06-04T13:30:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        {"ts": "2026-06-04T13:35:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ])
    store = BarStore(tmp_path)
    bars = store.bars("ABC", "5m")
    assert len(bars) == 3 and isinstance(bars[0], Bar)
    assert store.sessions("ABC") == [date(2026, 6, 3), date(2026, 6, 4)]

def test_missing_file_returns_empty(tmp_path):
    assert BarStore(tmp_path).bars("NOPE", "1h") == []
