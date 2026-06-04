# Liquidity Sweep Scanner — Design / Spec

## Context

**Goal:** Build a live, multi-symbol scanner that detects ICT-style liquidity sweeps (stop raids) on the 5-minute chart, then passes each raw sweep through a 3-part "probability equation" (RS/RW vs SPY/QQQ, spread/liquidity, R:R ≥ 2) to surface only high-quality, executable setups on a web dashboard.

**Why now:** The user has a Questrade account and an existing `tv-mcp` toolchain (Questrade data + TradingView + backtest + alert→compliance→execution rails). Rather than build in a vacuum, this scanner is the *brain* (detection + filters + dashboard) that consumes working Questrade data and hands qualified setups to rails that already exist.

**Two non-negotiable correctness requirements (user-emphasized):**
1. **Lookahead-bias lockdown** — HTF/daily levels (PDH/PDL) computed only from *completed prior* data, never the forming day. Pine: `request.security(sym,"D",high[1],lookahead=barmerge.lookahead_off)`. Python: level for session *D* = daily bar *D−1* only.
2. **Asymmetric wick-stop** — stop sits exactly behind the sweep wick extreme (`wick_low − buffer` long / `wick_high + buffer` short) so a true reversal cuts the loss at the tightest structural point; this is what makes R:R ≥ 2 reachable. `buffer` is tuned (ticks or ATR fraction) and must exceed current spread.

### Locked decisions
| Decision | Choice |
|---|---|
| Stack | **Staged hybrid:** Pine sandbox (Stage 0, disposable geometry/lookahead/stop proof) → Python system-of-record (Stage 1) → TradingView MCP bridge for verification + chart previews |
| Broker / data | **Questrade** (existing `tv-mcp` data path now; execution rails later) |
| Universe | **Dynamic in-play pre-filter** (~20–40 names/day from a candidate list) |
| Scope | **Signal-only decision-support** — dashboard surfaces QUALIFIED signals; clean handoff seam to `stage_order`/compliance rails as a later phase |
| HTF bias | **1-hour trend gate, ON for v1** — 1h-EMA, lookahead-safe (last closed 1h bar); toggleable, lift still measured in backtest |
| Re-arm | **Every qualifying sweep** (no per-level lock; optional cooldown param defaults 0) |
| Target (defines R:R) | **Opposite-side PD liquidity** (PDL sweep→PDH, PDH sweep→PDL); swing + VWAP stored as alternates |
| Session | **RTH, killzone-weighted** (scan 09:30–16:00 ET, emphasize 09:30–11:30 + 14:00–15:30; time-of-day is a backtest slice) |

### Operational prerequisites (block "live", not design)
- `reauthorize_questrade` — broker refresh currently failing (`Questrade rejected refresh: unknown`, token ~7d old).
- Confirm **real-time market-data package** — without it quotes are 15-min delayed; 5m *bar* detection tolerates mild delay, but the **spread / top-of-book filters and precise entries require real-time L1**.
- Restart execution daemon (only needed when the Phase 5 execution seam is wired).

---

## Architecture

Maps onto the repo's 3-layer model (`directives/` = SOPs, `execution/` = deterministic Python, orchestration = agent).

```
Candidate list ──> UniverseManager (daily pre-filter) ──> in-play set (~20-40)
                                                              │
Questrade data ──> DataFeed (REST candles + streaming L1) ────┤
                                                              ▼
                              per-symbol StateMachine (1m cadence, 5m-close decisions)
                                IDLE→WATCHING→SWEEP→CANDIDATE→QUALIFIED
                                              │
                        levels.py  detect.py  filters.py  (lookahead-safe)
                                              ▼
                                  SignalBus (QUALIFIED JSON)
                                     │                 │
                              WebSocketServer      (later) stage_order → compliance → Questrade
                                     ▼
                              Dashboard (filters | table | chart preview)
```

Single source of truth for tunables = **`execution/params.yaml`**; Pine Stage 0 mirrors the same values (anti-drift). Pine only ever implements the *core sweep geometry*, never the full probability stack.

---

## Parameters (`params.yaml` — all UI-configurable, all backtest-sliced)

| Group | Param | Default | Notes |
|---|---|---|---|
| Detection | `operating_tf` / `tick_cadence` | 5m / 1m | decisions on 5m **close** only (no intrabar repaint) |
| | `levels` | `[PDH, PDL]` | session_high/low, asian off for equities v1 |
| | `level_session` | RTH | prior RTH H/L |
| | `atr_len` | 14 (5m) | reference ATR `atr5` |
| | `pen_atr_frac` / `min_pen_ticks` | 0.10 / $0.03 | wick penetration = `max(min_pen_ticks, pen_atr_frac·atr5)` |
| | `max_reentry_bars` | 1 | same or next 5m bar (tunable 1–2) |
| | `confirm_vol` | false | sweep-confirmation volume gate (off by default; measured in backtest) |
| | `sustained_window_bars` / `sustained_baseline_bars` | 3 / 20 | ~15-min rolling window vs trailing baseline, on the 5m grid |
| | `sustained_mult` | 1.75 | window vol ≥ mult × baseline — replaces noisy single-5m-bar spike check |
| | `prox_atr` | 0.5·atr5 | WATCHING proximity band |
| RS/RW | `rs_window_min` | 20 | momentum window |
| | `rs_thresh` | **0.30%** | user suggested 0.5–1.0%; see Challenge #2 |
| | `bench_flat_max` | 0.20% | benchmark "flat" band |
| | `bench_map` | SPY default, QQQ for Nasdaq/tech | per-symbol |
| | `rs_must_beat_both` | false | strict mode: beat SPY *and* QQQ |
| Trend (1h) | `htf_trend_gate` | **true (ON v1)** | longs need 1h trend up, shorts 1h trend down |
| | `htf_ema_len` | 20 | EMA on **completed** 1h closes (lookahead-safe) |
| | `htf_require_slope` | false | also require EMA rising/falling (off for v1) |
| Liquidity | `min_adv_shares` | 1,000,000 | 20-day ADV floor |
| | `min_bar_dollar_vol` | $1,000,000 | per 5m bar |
| | `min_rvol` | 1.0 | today cum-vol vs 20d cum-vol-to-time |
| | `max_spread_abs` / `max_spread_pct` | $0.05 / 8 bps | pass if either |
| | `min_book_shares` | 2,000 (optional) | Questrade L1 bid+ask size |
| | `spread_risk_frac` | 0.33 | spread ≤ ⅓ of risk (ties stop↔cost) |
| R:R | `entry_mode` | reentry_close | |
| | `buf_ticks` / `buf_atr_frac` | $0.02 / 0.05·atr5 | `buffer=max(...)`, must ≥ spread |
| | `target` | opposite_PD | alternates (swing, VWAP) stored |
| | `min_rr` | 2.0 | |
| Policy | `rearm` / `cooldown_bars` | every_sweep / 0 | optional soft cap `max_signals_per_symbol_day` |
| | `session_window` / `killzones` | 09:30–16:00 / [09:30–11:30, 14:00–15:30] | ET |
| Universe | `candidate_list` | S&P500 + liquid ETFs | configurable |
| | `inplay_max` | 40 | |
| | `inplay_criteria` | RVOL>1.5, \|gap%\|>1, near PDH/PDL, price>$5, ADV>1M | |

---

## Level computation (lookahead-safe)

- **PDH/PDL** = high/low of the previous *completed* RTH session.
- **Pine (Stage 0):** `pdh = request.security(syminfo.tickerid,"D",high[1],lookahead=barmerge.lookahead_off)` (and `low[1]` for PDL). The `[1]` pins to the prior completed daily bar; `lookahead_off` prevents forward time-shift.
- **Python (Stage 1):** `level[session=D] = daily[D-1].high / .low`; the forming day never contributes to its own level. Cross-check the computed level against TradingView's rendered PDH/PDL via the MCP to prove parity.
- **Lookahead audit (test):** assert every level used at session *D* derives only from data with date ≤ *D−1*; assert every signal timestamp ≥ its 5m bar close.

---

## Sweep detection (pseudo-code)

```python
pen_min = max(min_pen_ticks*tick, pen_atr_frac*atr5)

# ---- Bullish sweep (long) against a downside level (e.g. PDL) ----
swept = bar[i].low < level - pen_min                  # strictly below, real wick
reentry_j = first j in [i .. i+max_reentry_bars] where
              bar[j].close > level                    # closed back inside
              and min(low, i..j) < level - pen_min     # sweep wick still valid
              and (not confirm_vol or sustained_volume_ok(bars, j))   # ~15m sustained vol, lookahead-safe
if swept and reentry_j is not None:
    wick_extreme = min(low, i..reentry_j)
    emit_candidate(direction="long", level_type, level,
                   wick_extreme, entry_bar=reentry_j)

# ---- Bearish sweep (short) against an upside level (e.g. PDH): mirror ----
swept = bar[i].high > level + pen_min
reentry_j = first j where bar[j].close < level and max(high,i..j) > level+pen_min and (sustained vol if confirm_vol)
wick_extreme = max(high, i..reentry_j)
```

Decisions fire **only on 5m close**. Detection runs on the 1m cadence but evaluates closed 5m bars. Volume confirmation (when enabled) is a ~15-minute *sustained* read — the volume of the `sustained_window_bars` completed 5m bars ending at the re-entry bar vs `sustained_mult` × a trailing baseline — chosen over a single-5m-bar spike to mark genuine institutional displacement without widening the wick-stop or peeking at an unclosed 15m bar.

---

## Probability filters

**3.1 RS/RW**
```python
ret_sym   = price_sym[t]/price_sym[t-N] - 1          # N = rs_window_min
ret_bench = price_bench[t]/price_bench[t-N] - 1       # bench by bench_map
RS = ret_sym - ret_bench
long_ok  = RS >= +rs_thresh and ret_bench <=  bench_flat_max
short_ok = RS <= -rs_thresh and ret_bench >= -bench_flat_max
# also store rs_day (vs prior close); optional rs_must_beat_both
```
Conflict resolution: primary benchmark from `bench_map`; `rs_must_beat_both` toggles requiring outperformance vs SPY *and* QQQ.

**3.2 Spread & liquidity (boolean)**
```python
liquidity_ok = (adv_20d >= min_adv_shares)
  and (bar.volume*bar.close >= min_bar_dollar_vol)
  and (rvol_today >= min_rvol)
  and ((ask-bid) <= max_spread_abs or (ask-bid)/mid <= max_spread_pct)
  and (bid_size+ask_size >= min_book_shares)          # optional
  and ((ask-bid) <= spread_risk_frac * risk)          # spread can't eat the tight stop
```

**3.3 R:R**
```python
entry  = reentry_close
buffer = max(buf_ticks*tick, buf_atr_frac*atr5, current_spread)
stop   = wick_extreme - buffer   (long)  |  wick_extreme + buffer   (short)
target = PDH (long) | PDL (short)                     # opposite-side PD liquidity
risk   = abs(entry-stop);  reward = abs(target-entry);  rr = reward/risk
rr_ok  = rr >= min_rr
# store alt targets (nearest_swing, vwap) + their rr for UI switching
```
**3.4 HTF 1-hour trend gate (ON for v1)**
```python
# trend from COMPLETED 1h closes only (lookahead-safe; forming 1h bar excluded by caller)
htf = "up" if last_closed_1h_close > ema(closed_1h_closes, htf_ema_len) else "down"
trend_ok = (not htf_trend_gate) \
    or (direction == "long"  and htf == "up") \
    or (direction == "short" and htf == "down")
```
The 5m sweep stays the precision trigger; the 15m sustained-volume read and this 1h trend form a clean 4:1 confirmation/bias ratio above it.

A setup is **QUALIFIED** iff `(long_ok or short_ok) and liquidity_ok and rr_ok and trend_ok`.

---

## State machine (per symbol, re-arm = every sweep)

| State | Enter when | Exit / transition | Stored |
|---|---|---|---|
| IDLE | price > `prox_atr` from all levels | → WATCHING when within band | — |
| WATCHING_LEVEL | within `prox_atr` of a level | → SWEEP on pen_min breach; → IDLE if drifts away | level_id, type, price |
| SWEEP_IN_PROGRESS | 5m wick breached level by ≥ pen_min | → CANDIDATE on close-back-inside within `max_reentry_bars`; → WATCHING if window expires | sweep_start_ts, running wick_extreme |
| CANDIDATE_SIGNAL | re-entry close confirmed | → QUALIFIED if all filters pass; → WATCHING else | reentry_ts, entry/stop/target, metrics snapshot |
| QUALIFIED_SIGNAL | filters pass | emit → return to WATCHING (every-sweep re-arm) | full signal record |

Optional `cooldown_bars` / `max_signals_per_symbol_day` available but default permissive.

---

## Signal JSON schema

```json
{
  "signal_id": "AAPL-PDL-20260604T1435",
  "symbol": "AAPL",
  "direction": "long",
  "level_type": "PDL",
  "level_price": 187.40,
  "sweep_time": "2026-06-04T14:30:00-04:00",
  "reentry_time": "2026-06-04T14:35:00-04:00",
  "wick_extreme": 187.05,
  "entry_price": 187.55,
  "stop_price": 186.98,
  "target_price": 190.10,
  "alt_targets": {"nearest_swing": 188.90, "vwap": 188.30},
  "risk": 0.57, "reward": 2.55, "rr": 4.47,
  "rs_score": 0.41, "rs_window_min": 20, "benchmark": "QQQ",
  "spread_bps": 4.2, "spread_abs": 0.03,
  "volume_context": {"rvol": 1.8, "adv_20d": 52000000, "bar_dollar_vol": 9800000},
  "htf_bias": "up",
  "killzone": "ny_open",
  "mode": "live",
  "qualified": true
}
```

---

## Backtest framework

- **Inputs:** 1m + 5m OHLCV + daily levels for the candidate universe; SPY/QQQ intraday for RS; spreads from Questrade `BID_ASK` candles where available, else modeled `spread = f(price, ADV)`.
- **Pipeline:** generate raw sweeps → apply 3 filters → simulate trades.
- **Lookahead safety:** levels from D−1 only; signals on 5m close; **path resolution via 1m sub-bars** when a 5m bar straddles both stop and target (else assume stop-first, worst case).
- **Fills:** entry = reentry close + slippage (½ modeled spread); exit at first of stop/target on 1m path.
- **Stats:** win rate, avg R, expectancy (R), profit factor, R:R distribution, trade duration.
- **Slices:** time-of-day bucket, level type (PDH/PDL), RS decile, liquidity bucket, `htf_bias` on/off.
- **First knobs to tune:** `rs_thresh` + `rs_window_min`, `pen_atr_frac`, `max_reentry_bars`, target definition. Measure HTF-bias lift and every-sweep overtrading cost (see Challenges).

---

## Dashboard (component breakdown — no production code yet)

**Backend (Python):** `UniverseManager` (daily pre-filter), `DataFeed` (Questrade REST+stream), `ScannerEngine` (per-symbol `StateMachine`), `SignalBus` (emits QUALIFIED JSON), `WebSocketServer` (push), `RestApi` (params, signal history).

**Frontend (React or vanilla):**
- `FilterPanel` (left) — min RS, min R:R, min RVOL, time window, level types, bias toggle.
- `SignalTable` (center) — ticker, dir, sweep time, level type, entry/stop/target, R:R, RS, spread, volume context; blink/badge for signals < N min old; click → full chart.
- `ChartPreview` (right) — lightweight-charts or TradingView embed with level + wick + entry/stop/target marked (preview image can come from the TradingView MCP screenshot).
- WS client + signal store + highlight-last-N-min.

---

## Build phases

| Phase | Deliverable | Tools/files |
|---|---|---|
| 0 | **Pine sandbox** — prove sweep geometry, `lookahead_off`, wick-stop, R:R on 10–20 names; eyeball + rough stats | `tradingview` MCP, `backtest-runner` skill, `sandbox/liquidity_sweep.pine` |
| 1 | **Python core** — `params.yaml`, `questrade_client.py`, `levels.py` (lookahead-safe), `detect.py`, `filters.py`, signal schema; unit tests; level parity vs TradingView | `execution/`, `directives/compute_levels.md`, `detect_sweeps.md`, `probability_filters.md` |
| 2 | **Backtest harness** — candidate list, run, stats, slices; tune thresholds | `execution/backtest.py`, `directives/run_backtest.md` |
| 3 | **Live scanner MVP** — `universe.py` pre-filter + 1m polling loop, state machine, emit signals to JSON/console | `execution/scanner.py`, `directives/run_scanner.md` |
| 4 | **Dashboard** — `ws_server.py` + React frontend (table + chart preview); upgrade to streaming L1 | `execution/ws_server.py`, `frontend/` |
| 5 (later) | **Execution seam** — qualified signal → `stage_order` → `check_compliance_limits` → `place_order_live` (approval-gated) | existing `tv-mcp` rails |

---

## Challenges flagged (honest pushback)

1. **Every-sweep re-arm → overtrading risk.** With no per-level lock, a chop day can spam the same level. Recommend keeping `cooldown_bars`/`max_signals_per_symbol_day` available and explicitly measuring overtrading cost in the backtest before going fully permissive live.
2. **RS threshold.** 0.5–1.0% over 20 min is large intraday; defaulting to **0.30%** and tuning by RS-decile backtest. Revisit after data.
3. **Distant opposite-PD target → high R:R but lower hit-rate.** R:R gate won't catch "too far to reach." The backtest must report hit-rate by target-distance; consider the scale-out variant (stored alternates make this cheap to test later).
4. **HTF 1h-trend gate is ON for v1.** It encodes "trade with the higher-timeframe draw," but Phase 2 must still quantify its lift (toggle it off in the backtest) so the gate rests on evidence, not aesthetics — and so we can see how many otherwise-valid sweeps it filters out.

---

## Verification

- **Unit:** synthetic 5m sequences that should/shouldn't trigger (wick just short of `pen_min`, no close-back-inside, late re-entry); R/Reward/RR arithmetic; benchmark RS sign.
- **Lookahead audit:** automated assertions (levels ≤ D−1; signal ts ≥ 5m close); shift-test the backtest for leakage.
- **Integration replay:** run a known sweep day for SPY + a couple single names through Python; confirm expected signals; render each on TradingView via MCP, screenshot, eyeball geometry + stop placement.
- **Backtest sanity:** positive in-sample expectancy; slice tables populate; spread model sane vs `BID_ASK` candles.
- **Dashboard:** feed a recorded signal → appears in table, blinks, chart preview marks level/wick/entry/stop/target.
