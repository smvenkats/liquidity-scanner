# Hybrid Signal Ledger and EVM Engine Refactor Design

Date: 2026-06-25
Status: Draft for review

## Purpose

Refactor the scanner in two coordinated phases:

1. Stabilize the current Python equities liquidity scanner by adding a clear signal ledger boundary, date-aware active/history behavior, and minimal outcome/status fields.
2. Define a future Rust or Go EVM liquidity scanner engine that can emit the same ledger-shaped events without destabilizing the current Railway deployment.

The immediate user pain is that old triggered rows remain visible and the dashboard only displays time, not the triggering date or signal outcome. The broader architectural goal is to prepare the system for lower-latency, multi-source scanner engines while keeping the existing decision-support workflow working.

## Current State

The current production path is:

`Questrade/yfinance backfill -> BarStore -> scan_once/tier_scan -> signals.jsonl -> FastAPI/WebSocket dashboard`

Important constraints:

- The current scanner is equities-focused, not EVM/DEX-focused.
- `signals.jsonl` is both audit log and dashboard backlog source.
- The dashboard receives the full backlog on WebSocket connect.
- UI timestamps render as time-only in ET, so prior-day rows are hard to distinguish from today's rows.
- Signal execution is decision-support only. No live order placement is in scope.
- Railway deployment and Basic Auth must remain intact.

## Goals

- Make today's live scanner view unambiguous.
- Preserve historical signals for audit and later review.
- Add a small ledger contract that can be shared by the current Python scanner and a future Rust/Go EVM scanner.
- Avoid speculative execution features or a large rewrite.
- Keep changes testable with the existing Python test suite.

## Non-Goals

- No live trading or order placement.
- No Rust/Go implementation in the first implementation slice.
- No database migration in the first slice. JSONL remains the storage format for this refactor.
- No broad dashboard redesign beyond date/status clarity.
- No EVM RPC, mempool, DEX, or simulation integration in the first slice.

## Recommended Approach

Use a hybrid roadmap:

1. First, refactor the current Python scanner around a ledger-shaped signal event.
2. Then, document the Rust/Go EVM scanner as a separate future producer of the same ledger event schema.

This avoids forcing blockchain infrastructure concepts into the current equities scanner while still creating the boundary needed for a next-generation engine.

## Signal Ledger Contract

Introduce a canonical signal ledger event shape. Existing signal fields remain, with added metadata:

- `signal_id`: stable unique ID.
- `source`: initially `equities_sweep_python`.
- `asset_type`: initially `equity`; future values can include `evm_token` or `dex_pool`.
- `symbol`: current equity ticker.
- `market_date`: ET trading date for current scanner signals.
- `created_at`: UTC timestamp when the scanner emitted the event.
- `triggered_at`: signal trigger timestamp, normally current `reentry_time`.
- `status`: `active`, `resolved`, `expired`, or `invalidated`.
- `outcome`: null in the first slice; a later grading slice can set `target`, `stop`, `timeout`, `manual`, or `unknown`.
- `evaluated_at`: null initially; timestamp when outcome is known.
- `payload`: scanner-specific fields already present today, such as direction, level, entry, stop, target, rr, RS score, volume context, killzone, and htf bias.

The first implementation keeps a flat JSON object for compatibility, but the code treats these metadata fields as first-class.

## Current Scanner Slice

### Data Flow

Current flow remains:

`run_scan -> qualify signals -> append ledger events -> dashboard backlog/live stream`

Changes:

- Signal emission adds ledger metadata before writing.
- Backlog loading defaults to current ET `market_date` and active-like statuses.
- Full history remains available through a separate loader option or future endpoint.
- The dashboard displays full date and time for table rows, preview header, and health timestamps.

### Active Versus Historical Signals

Default dashboard behavior:

- Show today's signals by `market_date`.
- Include `active` signals by default.
- Keep historical rows in storage but do not mix them into the live table.

History behavior:

- First slice keeps history hidden from the default live table.
- A later slice can add a `History` filter or endpoint.

### Outcome Tracking

First slice:

- Add status fields with default `active`.
- Do not attempt automatic target/stop grading in the first slice.

Later slice:

- Use available 5m bars after `triggered_at` to mark `target`, `stop`, or `timeout`.
- Store `outcome_r` if enough price data exists.

## EVM Engine Architecture

Future low-latency engine should be a separate Rust or Go service that emits the same ledger event contract.

Recommended future flow:

`chain ingestion -> normalized event bus -> DEX state graph -> simulation/risk engine -> signal ledger -> dashboard/API`

Core components:

- Chain ingestion adapters for WebSocket RPC, full-node subscriptions, and optional gRPC/Substreams-style feeds.
- Canonical event model keyed by `chain_id`, `block_number`, `block_hash`, `tx_hash`, and `log_index`.
- DEX state graph with per-protocol adapters for v2, v3, and v4-style pools/hooks.
- Simulation/risk engine for buy/sell simulation, honeypot checks, slippage, fees, proxy risk, and reorg awareness.
- Ledger publisher that maps EVM findings into the shared signal event schema.

This service should not replace the Python scanner at first. It should run as a parallel producer once the ledger boundary is stable.

## Error Handling

- Bad JSONL rows continue to be skipped instead of killing the dashboard.
- Missing metadata on older rows should degrade safely:
  - infer `market_date` from `reentry_time` when possible;
  - default `status` to `active`;
  - default `source` to `equities_sweep_python`.
- If a signal lacks a parseable trigger timestamp, keep it out of today's default backlog and allow it only in history mode.

## Testing Strategy

Add focused tests for:

- Ledger metadata creation.
- ET `market_date` derivation.
- Backlog loading that excludes prior-day rows by default.
- Compatibility with older signal rows lacking new metadata.
- WebSocket backlog behavior.
- Dashboard timestamp formatter showing date plus ET time.

Run full verification:

`python -m pytest -q`

For dashboard JavaScript, keep the existing inline syntax check pattern used in prior sessions.

## Rollout Plan

1. Add ledger metadata helpers and tests.
2. Update signal emission to write metadata while preserving existing fields.
3. Update dashboard feed loading to default to today's active rows.
4. Update UI timestamp formatting to include date and time.
5. Add optional status display column or compact status badge.
6. Verify full test suite and dashboard JavaScript.
7. Update `.claude/project-log.md` with the new current state.
8. After the Python slice is stable, write a dedicated Rust/Go EVM engine architecture spec.

## Decisions

- Keep first-slice storage as JSONL.
- Show a compact status column in the dashboard.
- Defer automatic outcome grading to a separate follow-up slice.
