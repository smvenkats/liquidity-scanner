# tests/test_dash_feed.py
import json
from datetime import datetime, timedelta
from execution.models import Bar
from dashboard.feed import load_signals, JsonlTailer, bars_window

def test_load_signals_reads_jsonl_and_handles_missing(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"symbol":"A","rr":3}\n{"symbol":"B","rr":4}\n')
    got = load_signals(p)
    assert [g["symbol"] for g in got] == ["A", "B"]
    assert load_signals(tmp_path / "nope.jsonl") == []

def test_jsonl_tailer_yields_only_new_complete_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"n":1}\n{"n":2}\n')
    t = JsonlTailer(p)
    assert [r["n"] for r in t.new_records()] == [1, 2]
    assert t.new_records() == []                      # nothing new
    with p.open("a") as f:
        f.write('{"n":3}\n{"n":4}')                   # last line has no newline yet
    assert [r["n"] for r in t.new_records()] == [3]   # only the complete line
    with p.open("a") as f:
        f.write('\n')                                 # complete line 4
    assert [r["n"] for r in t.new_records()] == [4]

def _b(ts, c):
    return Bar(ts=ts, o=c, h=c, l=c, c=c, v=1)

class _Store:
    def __init__(self, bars): self._bars = bars
    def bars(self, sym, tf): return self._bars

def test_bars_window_slices_around_center():
    base = datetime(2026, 6, 4, 13, 30)
    bars = [_b(base + timedelta(minutes=5 * i), 100 + i) for i in range(30)]
    w = bars_window(_Store(bars), "X", base + timedelta(minutes=5 * 20), before=4, after=2)
    assert [round(b.c) for b in w] == [116, 117, 118, 119, 120, 121, 122]  # idx16..22

def test_load_and_tailer_skip_malformed_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"n":1}\nNOT JSON\n{"n":2}\n')
    assert [r["n"] for r in load_signals(p)] == [1, 2]
    t = JsonlTailer(p)
    assert [r["n"] for r in t.new_records()] == [1, 2]
