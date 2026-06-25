# execution/scanner/sink.py
from __future__ import annotations
import json
from pathlib import Path

from execution.scanner.ledger import enrich_signal_record


def emit_signals(signals, path) -> int:
    """Append each signal as one JSON line. Returns the count written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(enrich_signal_record(sig.to_dict())) + "\n")
    return len(signals)
