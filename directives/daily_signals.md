# Directive: Daily Signal Feed (today's potential trades)

**Goal:** Surface today's liquidity-sweep setups, tiered A (1h-aligned) / B (reversal),
each with a sized ticket. Decision-support only — this never places orders.

**Prerequisite:** Fresh data. Run `python -m execution.data.backfill` first (refreshes
5m/1h/1d for the universe into `data/bars/`; 1h/1d skip-if-complete, 5m re-pulls the
recent window). Token in `.env` (`QUESTRADE_REFRESH_TOKEN`).

**Run:** `python -m execution.scanner.daily`

**Tools:** `execution/scanner/daily.py` (CLI + render), `execution/scanner/tiers.py`
(`tier_scan` / `dedupe_setups` / `position_size`). Config: `execution/params.yaml`
(`data.universe`, `liquidity.min_rvol`, `signals.risk_per_trade_usd`).

**Tiers:**
- **A — aligned:** passes RS + liquidity + R:R AND the 1h-trend gate (high-conviction).
- **B — reversal watch:** passes RS + liquidity + R:R but opposes the 1h trend.
- **Rejected:** fails RS / liquidity / R:R — the non-negotiable tradability+quality screens.

**Edge cases / learnings:**
- 5m horizon: Questrade serves only ~60-90d of intraday, but today's session is always present.
- Sizing = floor(`risk_per_trade_usd` / per-share stop); tight stops -> large notional (shown).
- Dedup: one setup per (symbol, level_type, direction) — the earliest (actionable) trigger;
  the `every_sweep` re-arm otherwise repeats on each reclaim bar.
- `min_rvol` is 0.5 (not 1.0): the reclaim bar structurally prints less volume than the sweep
  bar it follows; 1.0 silently rejected almost everything.
- Daily cadence: `backfill` then `daily` each session.
