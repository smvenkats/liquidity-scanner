# Order Ticket (Phase 5, step 1) — Design Spec

**Date:** 2026-06-04
**Status:** Approved (brainstorm), pending implementation plan
**Author:** orchestration session

## Problem

The system produces qualified signals (tiered A/B daily feed) but stops at "here is a setup."
To act, the user still hand-computes side, share size, and the limit/stop prices under time
pressure. Phase 5's first step closes that gap: turn a `Signal` into a deterministic, sized,
guardrail-checked **order ticket** surfaced ready-to-fire in the daily feed.

## Decision: backend-agnostic ticket only (no placement)

The execution *backend* is deferred. Two Questrade consumers now exist — the liquidity-scanner
data provider (`.env` token) and the tv-mcp execution daemon (`state.db` token) — and they fight
over a shared single-use-rotating token chain (every data-provider auth invalidates tv-mcp's),
while tv-mcp's daemon is dead. Rather than resolve that now, this step builds only the
**deterministic Signal → order ticket**, which is identical regardless of backend. The "fire
adapter" (tv-mcp rails vs native) is a separate later phase.

This also keeps the agent strictly clear of the live-trade line: the ticket build places nothing.

## Goal

`build_ticket(signal, *, risk_usd, max_notional, max_qty) -> OrderTicket`, pure and deterministic,
rendered inline in the daily feed so each Tier-A/B signal is a ready-to-act ticket.

## Non-Goals (deferred to the fire-adapter phase)

- Any `stage_order` / `check_compliance_limits` / `place_order_live` call.
- Paper-vs-live flow; idempotency ledger; bracket/OCO mechanics.
- The tv-mcp broker reauth + daemon restart, and the two-token-chain resolution.

## Architecture

One small new unit + a render hook:

```
execution/execute/
  __init__.py
  ticket.py            # OrderTicket dataclass + build_ticket() (pure, deterministic)
execution/scanner/daily.py   # render each signal's ticket inline (modify)
execution/params.yaml        # new execution: caps block (modify)
```

`ticket.py` depends only on the `Signal` shape and `execution.scanner.tiers.position_size`
(reused for sizing — DRY). No I/O, no broker, no network.

## OrderTicket + build_ticket

```python
@dataclass
class OrderTicket:
    symbol: str
    side: str            # "buy" (long) | "sell" (short)
    qty: int
    order_type: str      # "limit"
    limit_price: float   # = signal entry (passive retest)
    stop_price: float
    target_price: float  # reference; bracket/OCO is the fire adapter's concern
    risk_per_share: float
    est_notional: float  # qty * limit_price
    warnings: list[str]
```

`build_ticket(signal, *, risk_usd, max_notional, max_qty)`:
- `side` = `"buy"` if `signal.direction == "long"` else `"sell"`.
- `qty = position_size(signal.risk, risk_usd)` (existing helper; floor, 0 if risk<=0).
- `limit_price = signal.entry_price`; `stop_price = signal.stop_price`; `target_price = signal.target_price`.
- `risk_per_share = signal.risk`; `est_notional = qty * limit_price`.
- **Guardrails — flag, never silently clamp:**
  - if `qty < 1`: warn `"risk budget too small for one share (stop too wide)"`.
  - if `est_notional > max_notional`: warn `"est notional ${est_notional:,.0f} exceeds max ${max_notional:,.0f}"`.
  - if `qty > max_qty`: warn `"qty {qty} exceeds max {max_qty}"`.
  - The reported `qty` stays the risk-based size; warnings flag the conflict so the user
    decides (silent clamping would change the risk profile behind their back).

Rationale: fixed-$ risk + tight stops can produce a large notional (e.g. $0.25 stop, $100 risk ->
400 sh -> ~$86k, over a $5k cap). The honest move is to show the risk-true size and flag the breach.

## params.yaml additions

```yaml
execution:
  per_order_max_notional_usd: 5000   # seeded from tv-mcp safety; independent of it
  per_order_max_qty: 10000
```

(`signals.risk_per_trade_usd` already exists and supplies `risk_usd`.)

## Integration — daily feed

`daily.py` builds a ticket per rendered signal and prints it inline under the existing entry/
stop/target line: `side qty @ limit  (~$notional)` plus any `warnings`. Tickets appear for both
Tier A and Tier B. No new command.

## Error handling

Pure function: no exceptions expected for well-formed signals. A zero/negative per-share risk
yields `qty 0` + a warning (never a crash or negative size). Caps are config; missing `execution`
block is a config error surfaced by `load_params` consumers (daily.py reads it).

## Testing (TDD)

Pure unit tests on `build_ticket`:
- side mapping long->buy, short->sell.
- sizing equals `position_size(risk, risk_usd)`; entry/stop/target wired through; est_notional = qty*limit.
- notional-cap warning fires when est_notional > max_notional (and not otherwise).
- qty-cap warning fires when qty > max_qty.
- sub-one-share warning when risk budget too small.
Plus a `daily.render` test that a ticket warning is displayed.

## Definition of done

1. `python -m pytest -q` green (existing + new ticket tests).
2. `python -m execution.scanner.daily` shows a sized ticket (with any cap warnings) under each
   Tier-A/B signal for the session.

## Out of scope / follow-ups

- **Fire adapter** (the actual placement): resolve the broker — either reauth tv-mcp from a
  SEPARATE Questrade app + restart its daemon and orchestrate its rails, or add order methods to
  the liquidity-scanner client with a native safety layer. Decide when ready to wire real fills.
- Idempotency ledger, bracket/OCO, paper-vs-live — all belong to the fire adapter.
