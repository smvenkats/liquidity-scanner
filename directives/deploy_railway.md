# Directive: Deploy the private family dashboard on Railway

Hosts `dashboard/server.py` (FastAPI + WebSocket) behind a shared login, with an in-process
periodic scan that refreshes data and appends signals the dashboard streams. Private use only.

## What's already in the repo
- `Dockerfile` (uvicorn web server) + `.dockerignore` (keeps secrets/data OUT of the image).
- `railway.toml` (dockerfile build + start command).
- Basic Auth (`dashboard/auth.py`), the scan scheduler (`dashboard/scheduler.py`), and the
  scan job (`execution/scanner/run_scan.py`).

## Steps in Railway (you do these — needs your account + the token)

1. **Service** — your repo is already connected; Railway builds from the `Dockerfile` on push.
2. **Add a Volume** to the service, mount path **`/data`** (persists signals, bars, token cache).
3. **Set service Variables** (Railway dashboard → Variables):
   | Variable | Value |
   |---|---|
   | `QUESTRADE_REFRESH_TOKEN` | your Questrade refresh token (from a Questrade personal app) |
   | `DASH_USER` | a family username, e.g. `family` |
   | `DASH_PASSWORD` | a strong shared password |
   | `SCAN_ENABLED` | `true` |
   | `SCAN_INTERVAL_MIN` | `60` |
   | `SIGNALS_PATH` | `/data/signals.jsonl` |
   | `BARS_DIR` | `/data/bars` |
   | `QUESTRADE_TOKEN_CACHE` | `/data/.questrade_token.json` |
   (Do NOT set `PORT` — Railway injects it.)
4. **Deploy**, then **Generate Domain** (Settings → Networking).
5. **Open the URL** → the browser prompts for the `DASH_USER`/`DASH_PASSWORD` login. ✅ auth works.

## Verify the data fetch (the one real risk)

Watch the **deploy logs** after the first scan (the first run does a full backfill, ~5 min):
- `"[scheduler] scan emitted N fresh signals"` → ✅ Questrade fetch works from Railway's IP.
- Repeated `QuestradeAPIError` / Cloudflare / 403 → ❌ the datacenter IP is blocked. **Fallback:**
  set `SCAN_ENABLED=false`, run the scan on your home machine (Windows Task Scheduler running
  `python -m execution.scanner.run_scan` — see below), and sync `signals.jsonl` + `bars/` up to
  the volume. The dashboard then only serves.

## Token hygiene

The dashboard auths to Questrade with `QUESTRADE_REFRESH_TOKEN` and caches the rotated token to
`/data/.questrade_token.json` on the volume. **Use a SEPARATE Questrade personal app** from any
other consumer (e.g. the tv-mcp execution daemon) — Questrade rotates the token on every refresh,
so two consumers sharing one app will invalidate each other.

## Local dev

`cp .env.example .env`, fill `DASH_USER`/`DASH_PASSWORD` (+ token if you want the scan), then:
`uvicorn dashboard.server:app --port 8000` → open http://localhost:8000. Without `SCAN_ENABLED=true`
no scan runs; point the dashboard at existing `.tmp/signals.jsonl` or run a manual
`python -m execution.scanner.run_scan` to populate it.
