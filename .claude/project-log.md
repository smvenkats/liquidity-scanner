# Project Log

Running log of work sessions on **liquidity-scanner**. **Newest session on top.**
At the END of every session, append a dated entry: what changed, current state, what's next.
(This replaces the old `HANDOVER.md`. Granular cross-session notes also live in
`.claude/projects/C--Users-smven-liquidity-scanner/memory/`.)

---

## Current State (2026-06-04)

- **`main`**, tests **147 passed / 1 skipped** (the skip = token-gated live smoke; skips when the
  local Questrade token is rotated/expired — see token conflict below).
- **Live:** private family dashboard on **Railway** (`liquidity-scanner-production.up.railway.app`),
  behind Basic Auth, with an in-process **market-hours-aware** scan. Verified end-to-end: auth,
  scan, WebSocket stream, and Questrade fetch from Railway's IP (no Cloudflare block).
- **Pipeline:** data layer (Questrade + yfinance) → tiered sweep detection → daily feed (CLI
  `daily.py`) + hosted dashboard → order tickets (`build_ticket`). **Decision-support only — no
  live order execution is built.**

### Run commands
- Tests: `python -m pytest -q`  (set `$env:PYTHONPATH="."` for ad-hoc scripts)
- Daily signals (CLI): `python -m execution.data.backfill` then `python -m execution.scanner.daily`
- Dashboard (local): `uvicorn dashboard.server:app --port 8000` (needs `DASH_USER`/`DASH_PASSWORD`)
- Deploy / re-deploy: push to `main` → Railway builds. Runbook: `directives/deploy_railway.md`.

### Architecture map
- `execution/data/` — bulk data provider (Questrade client, paginate, normalize, yfinance, backfill, env)
- `execution/scanner/` — detection engine, tiers (A/B), daily feed, run_scan, sink, emit_test_signal
- `execution/execute/` — `ticket.py` (Signal → OrderTicket)
- `execution/backtest/` — BarStore + backtest harness
- `dashboard/` — FastAPI server (auth, /ws, /bars, /test-signal), scheduler, static SPA
- `directives/` — SOPs (backfill, daily_signals, deploy_railway, run_*)

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
