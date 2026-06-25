# Hybrid Signal Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live dashboard date-aware and active-only by default while preserving JSONL signal history and preparing a shared event contract for future EVM scanner producers.

**Architecture:** Keep JSONL as the first-slice storage layer. Add a focused ledger helper module that enriches current flat signal rows with first-class metadata, then make dashboard backlog loading filter to today's ET market date and active-like statuses. The dashboard keeps its current FastAPI/WebSocket shape and renders full ET date/time plus a compact status column.

**Tech Stack:** Python 3, pytest, FastAPI WebSocket backlog, JSONL signal storage, vanilla dashboard JavaScript.

## Global Constraints

- No live trading or order placement.
- No Rust/Go implementation in the first implementation slice.
- No database migration in the first slice. JSONL remains the storage format for this refactor.
- No broad dashboard redesign beyond date/status clarity.
- No EVM RPC, mempool, DEX, or simulation integration in the first slice.
- Preserve Railway deployment and Basic Auth behavior.
- Keep bad JSONL rows non-fatal.

---

### Task 1: Ledger Metadata Helpers

**Files:**
- Create: `execution/scanner/ledger.py`
- Test: `tests/test_signal_ledger.py`

**Interfaces:**
- Produces: `market_date_et(iso_or_dt) -> str | None`
- Produces: `enrich_signal_record(record: dict, *, created_at: datetime | None = None) -> dict`
- Produces: `is_active_today(record: dict, *, now: datetime | None = None) -> bool`

- [ ] **Step 1: Write failing tests**

Create tests proving that metadata is added to new rows, older rows infer `market_date` from `reentry_time`, prior-day rows are not active today, malformed rows are not active today, and `resolved` rows do not appear in the active live view.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest tests/test_signal_ledger.py -q`
Expected: import failure for `execution.scanner.ledger`.

- [ ] **Step 3: Implement minimal helper module**

Create `execution/scanner/ledger.py` with ET date derivation, compatibility defaults, and active-today predicate.

- [ ] **Step 4: Verify focused tests pass**

Run: `python -m pytest tests/test_signal_ledger.py -q`
Expected: all tests in that file pass.

### Task 2: Emit Ledger Metadata

**Files:**
- Modify: `execution/scanner/sink.py`
- Test: `tests/test_scan_sink.py`

**Interfaces:**
- Consumes: `enrich_signal_record(record: dict, *, created_at: datetime | None = None) -> dict`
- Produces: JSONL rows that include `source`, `asset_type`, `market_date`, `created_at`, `triggered_at`, `status`, `outcome`, and `evaluated_at`.

- [ ] **Step 1: Write failing sink test**

Extend the sink test to assert emitted rows include the ledger metadata while retaining existing flat signal fields.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest tests/test_scan_sink.py -q`
Expected: failure because emitted rows do not yet include metadata.

- [ ] **Step 3: Update sink implementation**

Wrap `sig.to_dict()` through `enrich_signal_record()` before writing JSONL.

- [ ] **Step 4: Verify focused tests pass**

Run: `python -m pytest tests/test_scan_sink.py tests/test_signal_ledger.py -q`
Expected: all selected tests pass.

### Task 3: Active Backlog Filtering

**Files:**
- Modify: `dashboard/feed.py`
- Modify: `dashboard/server.py`
- Test: `tests/test_dash_feed.py`
- Test: `tests/test_dash_server.py`

**Interfaces:**
- Produces: `load_signals(path, *, active_only: bool = False, now: datetime | None = None) -> list[dict]`
- WebSocket backlog calls `load_signals(SIGNALS_PATH, active_only=True)`.

- [ ] **Step 1: Write failing feed/server tests**

Add tests showing `load_signals(active_only=True)` excludes prior-day and resolved rows, and WebSocket backlog sends only today's active rows.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -m pytest tests/test_dash_feed.py tests/test_dash_server.py -q`
Expected: failure because `load_signals` lacks `active_only` and server still sends all rows.

- [ ] **Step 3: Update feed and server**

Use ledger enrichment while reading rows and filter active backlog in the WebSocket connect path.

- [ ] **Step 4: Verify focused tests pass**

Run: `python -m pytest tests/test_dash_feed.py tests/test_dash_server.py -q`
Expected: all selected tests pass.

### Task 4: Date/Status Dashboard Rendering

**Files:**
- Modify: `dashboard/static/index.html`
- Test: `tests/test_dash_static.py`

**Interfaces:**
- Dashboard table includes `status` column.
- `tstr()` renders month, day, hour, and minute in America/New_York.

- [ ] **Step 1: Write failing static test**

Add a text-level test asserting the table has a status column and the timestamp formatter includes month/day options.

- [ ] **Step 2: Run focused test to verify failure**

Run: `python -m pytest tests/test_dash_static.py -q`
Expected: failure because status/date rendering is absent.

- [ ] **Step 3: Update dashboard HTML/JS**

Add status column, render status values, and change timestamp formatting to full date plus time.

- [ ] **Step 4: Verify focused tests pass**

Run: `python -m pytest tests/test_dash_static.py -q`
Expected: all selected tests pass.

### Task 5: Project Log and Full Verification

**Files:**
- Modify: `.claude/project-log.md`

**Interfaces:**
- Current State reflects signal ledger metadata, today-only active backlog, date-aware dashboard, and first-slice scope.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -q`
Expected: all non-token-gated tests pass; the known live smoke may skip.

- [ ] **Step 2: Run dashboard JavaScript syntax check**

Run an inline extraction/syntax check for the `<script>` block in `dashboard/static/index.html`.
Expected: syntax check exits 0.

- [ ] **Step 3: Update `.claude/project-log.md`**

Prepend a dated session entry with changed files, verification output, and remaining next steps.

- [ ] **Step 4: Review git diff**

Run: `git diff --stat` and `git diff --check`
Expected: scoped changes, no whitespace errors.
