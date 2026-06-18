# dashboard/scheduler.py
"""Background thread that runs the scan on a timer for the hosted dashboard.

Gated by SCAN_ENABLED — set it false for the home-fetch-and-sync fallback, where the scan
runs on your home machine and only the synced signals.jsonl is served here.
"""
from __future__ import annotations
import os
import threading
import traceback
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def scan_enabled() -> bool:
    # Default OFF (fail-closed): tests/local never spawn a scan thread or hit the network.
    # The Railway runbook sets SCAN_ENABLED=true to turn the periodic scan on.
    return os.environ.get("SCAN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def is_market_hours(now_utc: datetime | None = None) -> bool:
    """True on weekdays 09:30-16:00 ET (US regular trading hours)."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(_ET)
    return now.weekday() < 5 and dtime(9, 30) <= now.time() <= dtime(16, 0)


def interval_seconds(now_utc: datetime | None = None) -> float:
    """Scan cadence: SCAN_INTERVAL_MIN during market hours, SCAN_IDLE_MIN otherwise."""
    rth = float(os.environ.get("SCAN_INTERVAL_MIN", "15"))
    idle = float(os.environ.get("SCAN_IDLE_MIN", "60"))
    return (rth if is_market_hours(now_utc) else idle) * 60.0


def start_scheduler(stop: threading.Event):
    """Start the periodic-scan daemon thread if SCAN_ENABLED. Returns the thread or None."""
    if not scan_enabled():
        return None
    out_dir = os.environ.get("BARS_DIR", "/data/bars")
    signals_path = os.environ.get("SIGNALS_PATH", "/data/signals.jsonl")
    status_path = os.environ.get("SCAN_STATUS_PATH", "/data/scan_status.json")

    def loop():
        from execution.config import load_params
        from execution.data.env import load_dotenv
        from execution.scanner.run_scan import run_scan
        load_dotenv()
        while not stop.is_set():
            try:
                params = load_params()
                n = run_scan(params, out_dir=out_dir, signals_path=signals_path,
                             benchmark=params["data"]["benchmark"],
                             status_path=status_path)
                print(f"[scheduler] scan emitted {n} fresh signals", flush=True)
            except Exception:
                print("[scheduler] scan failed:\n" + traceback.format_exc(), flush=True)
            stop.wait(interval_seconds())  # tighter during market hours, looser off-hours

    t = threading.Thread(target=loop, name="scan-scheduler", daemon=True)
    t.start()
    return t
