# Questrade Bulk Data Provider — Design Spec

**Date:** 2026-06-04
**Status:** Approved (brainstorm), pending implementation plan
**Author:** orchestration session

## Problem

The backtest is data-limited: the tv-mcp/Questrade `get_ohlcv` path caps at **500 bars/request**
(~7 sessions of 5m), so the harness is directional-only, not statistically significant. The open
research question — **does the 1h-trend gate help or hurt?** — cannot be answered on 7 days × 4 names.

We need deep historical bars in the `BarStore` to run a meaningful `gate_lift` backtest. The 500-bar
limit is a *per-request* server cap on Questrade's `/markets/candles` endpoint — it is lifted by
**time-windowed pagination**, not by a different transport or vendor.

## Goal

A deterministic, self-contained data layer that backfills **2 years of 5m / 1h / 1d bars** for
**SPY + ~10 liquid, sweep-prone names** into the `BarStore` file format, with zero changes to the
detection/backtest engine. Then re-run `gate_lift` on real bulk history.

Target universe (tunable): `SPY` (benchmark) + `QQQ, AAPL, NVDA, TSLA, AMD, META, AMZN, MSFT, GOOGL, NFLX`.

## Non-Goals

- No live streaming / no daemon — this is a batch backfill tool.
- No order execution (that is Phase 5, parked).
- No interleaving of data sources *within* a single series.

## Architecture (Approach A — port + paginate)

Reuse the proven Questrade client from the sibling `odte-vwap-scanner` project by **porting** it
(self-contained copy), not importing across repos. The only genuinely new logic is pagination.

```
execution/data/
  __init__.py
  questrade_client.py   # PORTED from odte questrade_provider.py:
                        #   OAuth + single-use-token rotation + token cache,
                        #   transport ladder (urllib -> curl_cffi -> cloudscraper),
                        #   find_symbol_id, get_candles(symbol_id, start, end, interval).
                        #   Stripped of odte's config/DataProvider/Bar deps. read_md scope;
                        #   NO order methods ported (structurally cannot trade).
  yfinance_client.py    # Backup source for 1h/1d ONLY. fetch(symbol, tf, start, end) ->
                        #   normalized rows. Clamps to Yahoo horizons; warns loudly.
  paginate.py           # PURE: tf->interval map, per-tf window sizing, iter_windows(),
                        #   stitch(dedup-by-ts + sort). No I/O.
  normalize.py          # PURE: Questrade {start,open,high,low,close,volume} and yfinance
                        #   rows -> {ts,o,h,l,c,v}.
  backfill.py           # Orchestrator: per (symbol, tf) -> walk windows -> fetch ->
                        #   normalize -> stitch -> write {SYMBOL}_{tf}.json + manifest.
                        #   Source selection, fallback, gaps, resumability. Thin __main__ CLI.
directives/
  fetch_bulk_data.md    # SOP (matches run_backtest/run_scanner/run_dashboard).
```

**Separation of concerns:** `questrade_client`/`yfinance_client` = I/O (the proven/risky part);
`paginate`/`normalize` = pure logic (the new, fully unit-testable part); `backfill` = orchestration.

## Data sources & fallback

| tf | Primary | Backup | Notes |
|----|---------|--------|-------|
| 5m | Questrade | **none** | Yahoo caps 5m at ~60d; a fallback would silently gut the research series. 5m hard-fails loud if Questrade can't deliver. |
| 1h | Questrade | yfinance | Yahoo 1h reaches ~730d (covers 2yr). |
| 1d | Questrade | yfinance | Yahoo 1d = full history. |

Fallback is **per-series, never per-bar** (Yahoo split/dividend adjustments differ from Questrade raw;
mixing within a series creates discontinuities):
- **Systemic Questrade failure** (first request for a series fails hard — auth/entitlement): 1h/1d
  switch the *whole series* to yfinance; 5m records FAILED and stops.
- **Transient window failure** (intermittent network on a later window): retry; if still failing,
  record the missing range in `manifest.gaps` and continue. Never write a clean-looking file with a
  hidden hole.

## Pagination & window logic

500-candle cap is per request → each window must yield **< 500 candles even at extended-hours density**.
Conservative fixed windows + a hard guard (no adaptive shrinking in v1):

| tf | Questrade interval | window | worst-case candles | ~requests / symbol (2yr) |
|----|--------------------|--------|--------------------|--------------------------|
| 5m | `FiveMinutes` | 2 days | ~384 | ~365 |
| 1h | `OneHour` | 25 days | ~400 | ~30 |
| 1d | `OneDay` | 400 days | 400 | 2 |

- `iter_windows(start, end, window_days)` — pure; non-overlapping `(wstart, wend)` segments.
- **Truncation guard:** after each fetch, assert returned count `< 500`. If it ever trips, fail loud
  (do not write a truncated series). Window sizes live in `params.yaml` so they're tunable on calibration.
- `stitch(window_results)` — concatenate, **dedup by ts** (boundary safety), sort ascending.
- Empty windows (weekends/holidays → `[]`) skipped silently.
- `request_sleep_sec` (0.2s) between requests. ~400 req/symbol × 10 ≈ 4k requests, well under
  Questrade's ~30k/hr. HTTP 429 → exponential backoff + retry.

## Auth & token (own store)

Ported client keeps odte's exact, proven model:
- Seed: `QUESTRADE_REFRESH_TOKEN` in liquidity-scanner `.env`.
- Cache: `QUESTRADE_TOKEN_CACHE` -> `.questrade_token.json` at project root (gitignored).
- Single-use rotation: cached rotated token supersedes the `.env` seed; every exchange persists the
  new token; access token cached with expiry + 60s skew. Paste one fresh token once; it self-maintains.
- The user pastes the token themselves (agent never handles it). To avoid rotating/invalidating the
  tv-mcp and odte token chains, generate it from a **separate Questrade personal app**.
- Transport selectable via `QUESTRADE_HTTP_TRANSPORT` (default `auto`). `curl_cffi` in deps for best
  Cloudflare odds. yfinance needs no auth.

## Output format

- `{SYMBOL}_{tf}.json` — JSON array of normalized rows `{ts, o, h, l, c, v}` (the shape
  `Bar.from_questrade` already expects), into **`data/bars/`** (persistent, gitignored — bulk history
  is expensive to refetch, unlike the regenerable `.tmp` demo data).
- `data/bars/manifest.json` — per file: `source` (questrade/yfinance), `tf`, `covered_start`,
  `covered_end`, `row_count`, `fetched_at`, and any `gaps`. Provenance + actual coverage never ambiguous.
- `BarStore(root="data/bars")` consumes it with **zero engine change**; the backtest runner is just
  pointed at the new root.
- `.gitignore` updated for `.env`, `.questrade_token.json`, `data/bars/`.

## Resumability

Default **skip-if-complete**: if a file + manifest entry already covers the requested range, skip
(cheap reruns). `--force` refetches.

## params.yaml additions

```yaml
data:
  out_dir: "data/bars"
  benchmark: "SPY"
  universe: [QQQ, AAPL, NVDA, TSLA, AMD, META, AMZN, MSFT, GOOGL, NFLX]
  timeframes: ["5m", "1h", "1d"]
  lookback_years: 2
  request_sleep_sec: 0.2
  windows:
    "5m": { interval: "FiveMinutes", window_days: 2 }
    "1h": { interval: "OneHour",     window_days: 25 }
    "1d": { interval: "OneDay",      window_days: 400 }
```

## Testing (TDD)

- **Pure-logic unit tests (no network — the bulk):** `iter_windows` (boundaries, full-range coverage,
  range<window, exact multiples) · `stitch` (dedup-by-ts, sort, empty, boundary overlap) ·
  normalization (Questrade->rows, yfinance->rows, missing fields) · tf->interval map · the <500 guard.
- **Orchestration tests with a mocked client:** canned window responses -> stitched file content +
  manifest entries; the 5m-failure path writes no silent stub + records the gap; the 1h
  systemic-failure path flips the series to yfinance and the manifest `source` reflects it.
- **One live smoke test**, gated on a token being present (skipped when absent, like odte's `__main__`):
  fetch a small recent SPY window -> non-empty, ascending, normalized shape.
- Port odte's key client/transport tests (adapted) so the data layer is self-contained.

## Dependencies added

`curl_cffi` (Cloudflare transport), `yfinance` + `pandas` (1h/1d backup). Noted: the project is
light on deps today.

## Definition of done

1. `python -m pytest -q` green (existing 78 + new data-layer tests).
2. A real backfill run populates `data/bars/` with 2yr of 5m/1h/1d for the universe + manifest.
3. `gate_lift` re-run on the bulk data produces a statistically meaningful gate-on vs gate-off result
   — finally answering the open research question.

## Out of scope / follow-ups

- Phase 5 execution seam (parked; decisions preserved: prepare+present/paper-e2e, fixed-$ sizing,
  limit @ entry_price).
- Adaptive window shrinking (only if first-run calibration shows the fixed windows are wrong).
