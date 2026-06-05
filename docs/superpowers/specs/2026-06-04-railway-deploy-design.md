# Private Family Dashboard on Railway — Design Spec

**Date:** 2026-06-04
**Status:** Approved (brainstorm), implementing
**Audience:** the user + a few family members (private, behind a login)

## Goal

Host the existing FastAPI dashboard (`dashboard/server.py`) on Railway so a few family
members can view today's signals from anywhere, behind a shared login. One Railway service
runs the web server AND a periodic in-process scan that refreshes data and appends signals
to a JSONL on a persistent volume, which the dashboard streams.

## Scope / non-goals

- Private use only (not public): personal Questrade token + yfinance are fine; do NOT expose publicly.
- No per-user accounts, no billing — one shared Basic-Auth password.
- The rich tiered A/B + order-ticket *web* view is a fast-follow; MVP streams the signal feed
  (core-passing signals, real 1h-trend annotated) into the existing dashboard UI.

## Architecture (single Railway service + volume)

```
Railway service (one container):
  - uvicorn dashboard.server:app  (web, $PORT, Basic Auth on /, /bars, /ws)
  - in-process scheduler thread (SCAN_ENABLED): every SCAN_INTERVAL_MIN runs run_scan()
      -> backfill (refresh data) -> scan_once(gate off) -> annotate 1h trend
      -> dedup vs existing -> append fresh signals to SIGNALS_PATH
  - Volume mounted at /data: SIGNALS_PATH=/data/signals.jsonl, BARS_DIR=/data/bars,
      QUESTRADE_TOKEN_CACHE=/data/.questrade_token.json
```

Single service avoids Railway's per-service volume limitation (web + scan share one local volume).

## Components

| File | Responsibility |
|------|----------------|
| `dashboard/auth.py` | HTTP Basic Auth check (constant-time); FastAPI dependency + WS validator |
| `dashboard/server.py` | apply auth to `/`, `/bars`, `/ws` (modify) |
| `dashboard/scheduler.py` | background thread running `run_scan` every interval; gated by `SCAN_ENABLED` |
| `execution/scanner/run_scan.py` | backfill + scan_once(gate off) + annotate trend + dedup + emit |
| `Dockerfile` | python:3.12-slim, install requirements, run uvicorn |
| `railway.toml` | service + volume mount + start command |
| `.env.example` | env var contract |
| `directives/deploy_railway.md` | the runbook (user's Railway steps) |

## Auth (proportionate)

HTTP Basic Auth, one shared password from env `DASH_USER` / `DASH_PASSWORD`. Constant-time
compare. The HTTP routes use a FastAPI dependency; the `/ws` handshake validates the
`Authorization` header (browsers replay stored Basic creds on same-origin WS upgrades). If
either env var is unset, auth is OPEN (local dev) — the runbook requires setting them on Railway.

## run_scan (the scheduled job)

`run_scan(params, *, out_dir, signals_path, benchmark="SPY", do_backfill=True) -> int`:
1. (optional) `backfill` to refresh 5m/1h/1d into `out_dir`.
2. `scan_once(universe, BarStore(out_dir), {}, params, trend_gate=False, as_of_date=latest)` → core-passing signals (incl. reversals).
3. annotate each with its real 1h trend (reuse `tiers.annotate_trend`).
4. dedup vs `signal_id`s already in `signals_path`; append only fresh via `emit_signals`.
5. return count of fresh signals.

Each scan re-fetches 5m (~5 min for the universe) — hence a modest default interval (60 min).

## Env contract

| var | default | purpose |
|-----|---------|---------|
| `PORT` | 8000 | web port (Railway sets it) |
| `DASH_USER` / `DASH_PASSWORD` | (unset=open) | Basic Auth (set on Railway) |
| `QUESTRADE_REFRESH_TOKEN` | — | broker data token (set on Railway; user pastes) |
| `QUESTRADE_TOKEN_CACHE` | `/data/.questrade_token.json` | rotated-token cache on volume |
| `SIGNALS_PATH` | `/data/signals.jsonl` | feed file |
| `BARS_DIR` | `/data/bars` | bar store |
| `SCAN_ENABLED` | `true` | run the in-process scan; set `false` for the home-fetch fallback |
| `SCAN_INTERVAL_MIN` | `60` | scan cadence |

## Risk + fallback

The Questrade curl-cffi fetch may be Cloudflare-blocked from Railway's datacenter IP. Test on
first deploy. If blocked: set `SCAN_ENABLED=false`, run the scan at home (Windows Task Scheduler),
and sync `signals.jsonl`/`bars` to the volume (e.g. a small authed upload, or commit+pull). The
dashboard then only serves.

## Testing

- `dashboard/auth.py`: valid creds pass; wrong/missing creds 401; open when env unset (unit, TestClient).
- `run_scan`: with a fake feed + stub scan, emits only fresh (un-seen signal_id) records; dedups across calls.
- Local smoke: `uvicorn dashboard.server:app` with DASH_USER/PASSWORD set → 401 without creds, 200 with.

## Definition of done

1. `python -m pytest -q` green (existing + auth + run_scan tests).
2. Dashboard runs locally behind Basic Auth.
3. Deploy artifacts present; `directives/deploy_railway.md` is a complete runbook the user follows
   on Railway (set env vars incl. the token themselves, attach volume, deploy).
