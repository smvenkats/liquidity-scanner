# execution/scanner/emit_test_signal.py
"""Append a synthetic TEST signal to SIGNALS_PATH to verify the live dashboard end-to-end.

Run in the Railway Console (or locally): `python -m execution.scanner.emit_test_signal`
A 'TEST' row should appear on the dashboard within ~1s (the tailer polls every second).
These are clearly marked TEST so they're easy to spot and clear later.
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timezone
from pathlib import Path


def make_test_signal(now: datetime) -> dict:
    iso = now.isoformat()
    return {
        "signal_id": f"TEST-{now.strftime('%Y%m%dT%H%M%S')}",
        "symbol": "TEST", "direction": "long", "level_type": "PDL", "level_price": 100.0,
        "sweep_time": iso, "reentry_time": iso, "wick_extreme": 99.5,
        "entry_price": 100.0, "stop_price": 99.0, "target_price": 110.0, "alt_targets": {},
        "risk": 1.0, "reward": 10.0, "rr": 10.0, "rs_score": 0.01, "rs_window_min": 20,
        "benchmark": "SPY", "spread_bps": 1.0, "spread_abs": 0.01,
        "volume_context": {"rvol": 1.5, "adv": 1_000_000}, "htf_bias": "up",
        "killzone": "ny_open", "mode": "test", "qualified": True,
    }


if __name__ == "__main__":
    path = Path(os.environ.get("SIGNALS_PATH", ".tmp/signals.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    sig = make_test_signal(datetime.now(timezone.utc))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sig) + "\n")
    print(f"appended {sig['signal_id']} -> {path}  (watch the dashboard)")
