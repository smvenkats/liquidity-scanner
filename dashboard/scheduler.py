# dashboard/scheduler.py
"""Background thread that runs the scan on a timer for the hosted dashboard.

Gated by SCAN_ENABLED — set it false for the home-fetch-and-sync fallback, where the scan
runs on your home machine and only the synced signals.jsonl is served here.
"""
from __future__ import annotations
import os
import threading
import traceback


def scan_enabled() -> bool:
    # Default OFF (fail-closed): tests/local never spawn a scan thread or hit the network.
    # The Railway runbook sets SCAN_ENABLED=true to turn the periodic scan on.
    return os.environ.get("SCAN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def start_scheduler(stop: threading.Event):
    """Start the periodic-scan daemon thread if SCAN_ENABLED. Returns the thread or None."""
    if not scan_enabled():
        return None
    interval = float(os.environ.get("SCAN_INTERVAL_MIN", "60")) * 60.0
    out_dir = os.environ.get("BARS_DIR", "/data/bars")
    signals_path = os.environ.get("SIGNALS_PATH", "/data/signals.jsonl")

    def loop():
        from execution.config import load_params
        from execution.data.env import load_dotenv
        from execution.scanner.run_scan import run_scan
        load_dotenv()
        while not stop.is_set():
            try:
                params = load_params()
                n = run_scan(params, out_dir=out_dir, signals_path=signals_path,
                             benchmark=params["data"]["benchmark"])
                print(f"[scheduler] scan emitted {n} fresh signals", flush=True)
            except Exception:
                print("[scheduler] scan failed:\n" + traceback.format_exc(), flush=True)
            stop.wait(interval)

    t = threading.Thread(target=loop, name="scan-scheduler", daemon=True)
    t.start()
    return t
