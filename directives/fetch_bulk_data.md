# Directive: Fetch Bulk Historical Bars

**Goal:** Populate `data/bars/` with deep history so the backtest is statistically meaningful.

**Prerequisite (user does this, once):** Paste a fresh Questrade refresh token into
`liquidity-scanner/.env` as `QUESTRADE_REFRESH_TOKEN` (generate from a SEPARATE Questrade
personal app to avoid rotating the tv-mcp/odte token chains). Install deps:
`pip install -r requirements.txt`.

**Run:**
- `python -m execution.data.backfill`            # uses params.yaml data block (SPY + universe, 2yr)
- `python -m execution.data.backfill --symbols SPY AAPL --tfs 5m --years 1 --force`  # ad hoc

**Tools:** `execution/data/backfill.py` (orchestrator), `questrade_client.py` (primary),
`yfinance_client.py` (1h/1d backup). Config: `execution/params.yaml` `data:` block.

**Output:** `data/bars/{SYMBOL}_{tf}.json` (normalized {ts,o,h,l,c,v}) + `data/bars/manifest.json`
(source/coverage/gaps per series). Consume via `BarStore(root="data/bars")`.

**Edge cases / learnings:**
- 5m is Questrade-only and hard-fails loud (no yfinance fallback — Yahoo caps 5m at ~60d).
- If a window returns >=500 candles the run raises: shrink `data.windows.<tf>.window_days`.
- Questrade tokens are single-use-rotating; the client caches the rotated token in
  `.questrade_token.json`. A 400 on token exchange = stale/used token, regenerate it.
- Reruns skip series already complete in the manifest; use `--force` to refetch.
