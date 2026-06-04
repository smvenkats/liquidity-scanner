# Directive: Run the Backtest

**Goal:** Measure sweep-strategy performance on cached bars, including the 1h-trend-gate lift.

**Inputs:** cached `{SYMBOL}_{tf}.json` files (5m, 1h, 1d) under a data dir, plus the benchmark (SPY) 5m, produced by the data-seeding step.

**Tools:** `execution/backtest/runner.py` — `run_backtest(symbols, store, ...)` and `gate_lift(symbols, store, ...)`.

**Steps:**
1. Seed data: fetch multi-symbol x recent sessions via the tv-mcp `get_ohlcv` (500-bar cap) and write each series to `{SYMBOL}_{tf}.json`.
2. `store = BarStore(data_dir)`.
3. `run_backtest(symbols, store)` -> overall + by_killzone + by_level stats.
4. `gate_lift(symbols, store)` -> compare expectancy with the 1h-trend gate ON vs OFF.

**Edge cases / limits:**
- 500-bar feed cap -> ~7 sessions of 5m. Results are directional, not significant. Swap in a bulk source (more files) to scale.
- Spread is MODELED (no historical L1). ADV from daily bars. Straddle bars resolve stop-first.
