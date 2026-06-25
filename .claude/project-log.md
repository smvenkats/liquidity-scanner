# Project Log

Running log of work sessions on **liquidity-scanner**. **Newest session on top.**
At the END of every session, append a dated entry: what changed, current state, what's next.
(This replaces the old `HANDOVER.md`. Granular cross-session notes also live in
`.claude/projects/C--Users-smven-liquidity-scanner/memory/`.)

---

## Current State (2026-06-25)

- **`main`**, tests were last known **164 passed / 1 skipped** (the skip = token-gated live smoke; skips when the
  local Questrade token is rotated/expired — see token conflict below).
- **Live:** private family dashboard on **Railway** (`liquidity-scanner-production.up.railway.app`),
  behind Basic Auth, with an in-process **market-hours-aware** scan. Verified after the Questrade
  cache fix that Railway can emit real signals (`scan_once_raw=8`, `fresh=4`). Dashboard backlog now
  defaults to today's active ET-market-date signals, timestamps render with date + ET time, and signal
  rows carry first-slice ledger metadata (`source`, `asset_type`, `market_date`, `created_at`,
  `triggered_at`, `status`, `outcome`, `evaluated_at`).
- **Pipeline:** data layer (Questrade + yfinance) → tiered sweep detection → daily feed (CLI
  `daily.py`) + hosted dashboard → order tickets (`build_ticket`). **Decision-support only — no
  live order execution is built.**
- **Diagnostic note:** a temporary local script `.tmp/debug_drop_audit.py` now explains where
  candidates drop between cached bars and emitted signals. On the stale local `data/bars` snapshot
  (`as_of=2026-06-04`) it found **23 raw sweeps** and **3 core-passing gate-off setups**, with
  main candidate-level failures from RS (69.6%) and rvol/liquidity (52.2%). This proves the local
  detector can produce real candidates; production zero-results likely need Railway runtime
  inspection: data freshness/backfill, precondition skips, setup/file dedupe, or hosted env state.

### Run commands
- Tests: `python -m pytest -q`  (set `$env:PYTHONPATH="."` for ad-hoc scripts)
- Daily signals (CLI): `python -m execution.data.backfill` then `python -m execution.scanner.daily`
- Dashboard (local): `uvicorn dashboard.server:app --port 8000` (needs `DASH_USER`/`DASH_PASSWORD`)
- Deploy / re-deploy: push to `main` → Railway builds. Runbook: `directives/deploy_railway.md`.

### Architecture map
- `execution/data/` — bulk data provider (Questrade client, paginate, normalize, yfinance, backfill, env)
- `execution/scanner/` — detection engine, ledger metadata, tiers (A/B), daily feed, run_scan, sink, emit_test_signal
- `execution/execute/` — `ticket.py` (Signal → OrderTicket)
- `execution/backtest/` — BarStore + backtest harness
- `dashboard/` — FastAPI server (auth, /ws, /bars, /test-signal), scheduler, static SPA
- `directives/` — SOPs (backfill, daily_signals, deploy_railway, run_*)

---

## Session — 2026-06-25 (hybrid signal ledger first slice)

- Wrote and committed the approved hybrid design spec:
  `docs/superpowers/specs/2026-06-25-hybrid-signal-ledger-evm-engine-design.md`.
- Added implementation plan:
  `docs/superpowers/plans/2026-06-25-hybrid-signal-ledger.md`.
- Implemented the current-scanner cleanup slice:
  - Added `execution/scanner/ledger.py` with ET `market_date` derivation, compatibility metadata
    enrichment, and active-today filtering.
  - Updated `emit_signals()` so new JSONL rows include ledger metadata while preserving the existing
    flat signal fields.
  - Updated dashboard feed loading and WebSocket backlog so browser connects receive today's active
    signals by default; historical rows remain in JSONL but no longer mix into the live table.
  - Updated the dashboard table/preview to show date-aware ET timestamps and a compact `status`
    column.
  - Enriched tailed JSONL records too, so old-format `/test-signal` or manual appends still stream
    with compatibility defaults.
- Verification:
  - Focused TDD checks were run red/green for ledger, sink, feed/server backlog, tailer enrichment,
    and static dashboard contract.
  - `python -m pytest -q` -> **164 passed / 1 skipped / 1 expected yfinance warning**.
  - Inline dashboard JavaScript syntax check with `node --check` -> exit 0.
- Next:
  - Deploy/redeploy to Railway when ready and confirm old prior-day rows no longer appear in the live
    table while current active test/real signals still stream.
  - Separate follow-up slice can add automatic target/stop/timeout grading.
  - Separate future spec can detail the Rust/Go EVM engine producer once this ledger boundary is
    proven in production.

---

## Session — 2026-06-18 (RTH timing + dashboard scan health)

- After the Questrade token-cache parent fix deployed, Railway emitted real signals:
  `backfill_done ok_partial_skipped=33/33 failed={}`, `benchmark=SPY bench5_rows=8283`,
  `scan_once_raw=8`, `after_setup_dedupe=4 fresh=4`.
- User noticed dashboard times looked like premarket (for example 07:25 AM). Root distinction:
  the browser was rendering signal timestamps in local machine time, while the trading session
  logic must be judged in New York time. Also, backend `killzone()` was double-shifting timezone-aware
  exchange timestamps by subtracting four hours manually.
- Fixed the scanner timing path:
  - `killzone()` now converts timestamps through `America/New_York`, treating naive timestamps as UTC.
  - Added `market_date()` and `is_rth()` helpers.
  - `scan_once()` and `SymbolScanner.on_update()` now select the current market date via ET and only
    scan regular-session 5m bars, preventing premarket wick sweeps from qualifying.
- Added persistent scan-health plumbing:
  - `run_scan(..., status_path=...)` writes `last_scan_at`, `raw_candidates`, `after_setup_dedupe`,
    `emitted`, `benchmark_latest_5m`, `benchmark_5m_rows`, `failed_backfills`, and `abort`.
  - Scheduler writes `/data/scan_status.json` by default.
  - FastAPI serves `GET /scan-status`.
  - Dashboard sidebar shows last scan, raw candidates, emitted count, benchmark latest 5m, and failed
    backfills, while table/preview times now render explicitly as ET.
- Verification:
  - Focused regressions: ET killzone/RTH helper, premarket sweep exclusion, status roundtrip,
    dashboard `/scan-status`, and no-benchmark abort status.
  - `python -m pytest -q` -> **153 passed / 1 skipped / 1 expected yfinance warning**.
  - Inline dashboard JavaScript syntax check -> `inline js syntax ok`.
- Next watch item after Railway redeploy: confirm the sidebar scan health shows fresh `last scan`,
  `benchmark latest 5m` in ET, `failed backfills: none`, and nonzero `raw candidates` when setups exist.
- Follow-up Railway logs showed only browser/WebSocket and `/scan-status` request traffic, with no
  `[scan] backfill_start` or `[scheduler] scan emitted` lines. Added scheduler boot diagnostics so
  the next deploy prints either `[scheduler] disabled SCAN_ENABLED=...` or
  `[scheduler] enabled out_dir=... signals_path=... status_path=...`. Verification after this small
  patch: `python -m pytest -q` -> **154 passed / 1 skipped / 1 expected yfinance warning**.
- Subsequent Railway logs showed the scheduler running, but all 5m Questrade fetches failed with
  `QuestradeAuthError: Token exchange failed (HTTP 400...)`, causing `benchmark=SPY bench5_rows=0`
  and `abort=no_benchmark_5m`. Root cause is token-state recovery, not scanner timing: Questrade
  refresh tokens are single-use and the client normally prefers the cached rotated token over the env
  seed. If the `/data` cached token is stale/bad, updating `QUESTRADE_REFRESH_TOKEN` alone may not
  help. Added a narrow fallback: when cached-token exchange returns HTTP 400 and a different
  env token exists, try the env token once, persist the new rotation, and log the recovery. Verification:
  `python -m pytest -q` -> **155 passed / 1 skipped / 1 expected yfinance warning**.
- If Railway still shows HTTP 400 without the recovery log, the auth error now includes a
  secret-safe token-state hint (`cached`, `env`, `cached_env_same`, `env_fallback`) so the next log
  can distinguish missing env token vs same stale token vs env fallback attempted and failed.
  Verification: `python -m pytest -q` -> **156 passed / 1 skipped / 1 expected yfinance warning**.

---

## Session — 2026-06-18 (zero-real-signal diagnostic strategy)

- User reported Railway dashboard stays `live • connected` and mock injections work, but no real
  market signals have appeared for weeks. Reviewed the actual repo path instead of giving generic
  advice: `execution/scanner/run_scan.py`, `execution/scanner/tiers.py`, `execution/scanner/engine.py`,
  `execution/pipeline.py`, `dashboard/server.py`, `dashboard/scheduler.py`, and params.
- Key architecture reminder: hosted `run_scan` intentionally scans **gate-off core-passing**
  candidates (RS + liquidity + R:R) and annotates 1h trend afterward; frontend filters only hide/show
  already-emitted `signals.jsonl` rows. Killzone and max-age controls are frontend display filters,
  not backend gates. Current detection levels are **PDH/PDL only**; PWH/PWL are not currently wired.
- Added temporary local diagnostic script `.tmp/debug_drop_audit.py` (ignored by git) to report:
  pre-scan symbol drops, raw sweep count, RS/RR/liquidity subcheck failures, trend-if-gate-on,
  killzone distribution, setup dedupe, and existing `signals.jsonl` suppressions.
- Local run: `PYTHONPATH=. python .tmp/debug_drop_audit.py --bars-dir data/bars --signals-path .tmp/signals.jsonl --json-out .tmp/drop_audit.json`.
  Result on stale local cache: 10/10 symbols active, 23 raw sweeps, 3 core-passing gate-off setups,
  0 existing-signal suppressions, 16 one-per-setup dedupe suppressions; failures mainly RS/rvol.
- User-provided Railway logs showed the sharper production root symptom: **every important `*_5m`
  fetch failed**, including `SPY_5m`, `QQQ_5m`, AAPL/NVDA/TSLA/AMD/META/AMZN/MSFT/GOOGL/NFLX.
  Meanwhile `*_1h` was ok via yfinance and `*_1d` was skipped from existing cache. Since the scanner
  detects sweeps on 5m and anchors `as_of` from `SPY_5m`, this is upstream of frontend filters and
  explains repeated `[scheduler] scan emitted 0 fresh signals`.
- Added production diagnostic logging in `execution/data/backfill.py` and
  `execution/scanner/run_scan.py`: source-level backfill failures now print the exception type/message
  instead of collapsing to plain `failed`, and each scheduled scan logs backfill summary, benchmark
  5m row count/latest timestamp, raw signal count, setup-dedupe count, fresh count, and existing
  signal-id count. Verified locally with `python -m pytest -q` -> **147 passed / 1 skipped**.
- Follow-up Railway logs narrowed the issue to `SPY_5m` failing with
  `FileNotFoundError: /data/.questrade_token_v3.json`. Root cause: `QuestradeClient._save_cache()`
  tried to persist the rotated single-use token before ensuring the token-cache parent directory
  existed. Because SPY is first in the backfill order, SPY failed, but the in-memory access token
  let later symbols succeed. Fixed by creating the parent directory in `_save_cache()`, with a
  regression test. Verified locally with `python -m pytest -q` -> **148 passed / 1 skipped**.
- Next recommended diagnostic action: after Railway redeploys this logging patch, inspect one scheduler
  cycle for `SPY_5m: ok|partial`, `[scan] benchmark=SPY bench5_rows=...`, and
  `[scan] scan_once_raw=...`. If SPY 5m succeeds but no fresh signals emit, continue down the chain
  with raw-candidate/filter/dedupe counts.

---

## Session — 2026-06-04 (data layer → tiered signals → tickets → Railway deploy)

Four bodies of work, each brainstormed → spec'd → planned → TDD'd → reviewed → squash-merged:

1. **Bulk data layer** (`execution/data/`): curl-cffi Questrade client (read-only, ported from the
   sibling `odte-vwap-scanner`), time-windowed pagination (works around the 500-bar/request cap),
   yfinance backup for 1h/1d, normalized `{ts,o,h,l,c,v}` files + `manifest.json` into `data/bars/`,
   a dependency-free `.env` loader. BarStore consumes it with zero engine change.
2. **Tiered signal feed** (`execution/scanner/tiers.py` + `daily.py`): **Tier A** (1h-aligned) /
   **Tier B** (reversal/counter-trend) — *classifies instead of discarding*, resolving the
   unanswerable "does the 1h-gate help?" question. **`min_rvol` 1.0 → 0.5** (reclaim bar prints
   less volume than the sweep bar). Fixed-$ sizing. Dedupe to one setup per (symbol, level, dir).
3. **Order tickets** (`execution/execute/ticket.py`): `build_ticket(signal, risk_usd, max_notional,
   max_qty) → OrderTicket` (side, risk-based qty, limit @ entry, stop/target). Guardrails **flag,
   never silently clamp**, when a cap binds. Rendered in the daily feed. **Places nothing** — the
   "fire adapter" (real placement) is deferred.
4. **Railway deploy** (`dashboard/`, `Dockerfile`, `.dockerignore`, `railway.toml`,
   `directives/deploy_railway.md`): Basic Auth (**fail-closed on Railway** via `RAILWAY_ENVIRONMENT`
   guard), `SCAN_ENABLED`-gated in-process scan thread, `run_scan` (backfill → scan gate-off →
   dedupe → annotate 1h trend → append fresh), **market-hours cadence** (15 min RTH / 60 min idle),
   **inject-test-signal button** + `POST /test-signal`. Security-reviewed (fail-open fix, docs
   disabled, constant-time compare, path-traversal guard, `wss://` on HTTPS).

### Key findings — DO NOT relitigate
- **Questrade serves only ~60–90 days of intraday (5m/1h)** candles (HTTP 400 beyond); daily goes
  back years. Pagination can't fix *availability*. So sources are: 5m = Questrade ~60d, 1h =
  **yfinance** ~2yr, 1d = Questrade ~2yr. True deep 5m needs a paid vendor (Polygon/Databento).
- **Two-Questrade-token conflict:** the data provider (`.env` locally / Railway var) and the
  tv-mcp execution daemon (`state.db`) fight over ONE single-use-rotating token chain — each
  refresh invalidates the other. Railway's scans rotated the **local** token dead (hence the live
  smoke now skips locally). **Fix: a SEPARATE Questrade personal app per consumer.**
- Questrade fetch **works from Railway's datacenter IP** — the feared Cloudflare block did not happen.

### Next / open items
- **Fire adapter (Phase 5 step 2):** turn a ticket into a placed order. DEFERRED pending the
  token-conflict resolution (separate apps, or native execution in liquidity-scanner). The agent
  **cannot place live trades** — design is "prepare + present, user fires."
- **Tiered web view:** the dashboard streams a *flat* feed (gate-off core-passing, `htf_bias`
  annotated); it does NOT yet visually separate Tier A/B or show order tickets. Fast-follow.
- **Optional UI tunables:** surface backend thresholds (rvol / RS / RR) in the dashboard header,
  make them adjustable, label A/B per row.
- **Deep 5m backtest:** if it matters, drop a Polygon/Databento feed into `data/bars/` (BarStore is
  the swap point).
