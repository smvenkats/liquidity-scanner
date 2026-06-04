# Directive: Run the Dashboard

**Goal:** Watch QUALIFIED signals live in the browser.

**Tools:** `dashboard/server.py` (FastAPI). Env: `SIGNALS_PATH` (default `.tmp/signals.jsonl`), `BARS_DIR` (default `.tmp/bt_data`).

**Steps:**
1. Ensure the scanner is writing signals to `SIGNALS_PATH` (Phase 3 `emit_signals`).
2. Start: `python -m uvicorn dashboard.server:app --port 8787` (from the project root).
3. Open `http://localhost:8787`. The table streams signals; click a row for the sparkline.

**Notes:**
- Filtering is client-side. The `/bars` sparkline needs the symbol's 5m file in `BARS_DIR`.
- Signal-only display; no order actions here (execution = Phase 5).
- The tailer tracks line COUNT (append-only assumption). If signals.jsonl is rotated/truncated, restart the server.
