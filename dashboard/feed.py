# dashboard/feed.py
from __future__ import annotations
import json
from pathlib import Path
from execution.models import Bar
from execution.scanner.ledger import enrich_signal_record, is_active_today


def load_signals(path, *, active_only: bool = False, now=None) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = enrich_signal_record(json.loads(line))
        except json.JSONDecodeError:
            continue
        if active_only and not is_active_today(rec, now=now):
            continue
        out.append(rec)
    return out


class JsonlTailer:
    """Returns records appended to a JSONL file since the last call. Only complete
    (newline-terminated) lines are consumed; a partial trailing line is held back."""

    def __init__(self, path):
        self.path = Path(path)
        self._seen = 0

    def new_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        complete = lines if text.endswith("\n") else lines[:-1]
        fresh = complete[self._seen:]
        self._seen = len(complete)
        out = []
        for s in fresh:
            s = s.strip()
            if not s:
                continue
            try:
                out.append(enrich_signal_record(json.loads(s)))
            except json.JSONDecodeError:
                continue
        return out


def bars_window(store, symbol, center_ts, before=12, after=6) -> list[Bar]:
    bars = store.bars(symbol, "5m")   # assumed ascending by ts (BarStore sorts on load)
    idx = None
    for i, b in enumerate(bars):
        if b.ts <= center_ts:
            idx = i
        else:
            break
    if idx is None:
        return []
    return bars[max(0, idx - before): idx + after + 1]
