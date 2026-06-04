# Directive: Run the Live Scanner

**Goal:** Surface QUALIFIED liquidity-sweep signals on the in-play universe, emitting each once.

**Inputs:** a feed exposing `.bars(symbol, tf)` for 5m/1h/1d (+ benchmark 5m). Now: a BarStore over a directory refreshed by polling tv-mcp `get_ohlcv`. Later: a direct Questrade streaming adapter.

**Tools:**
- `execution/scanner/universe.py` - `select_inplay(symbols, feed, params)` -> today's in-play names.
- `execution/scanner/engine.py` - `scan_once(symbols, feed, states, params)` -> new qualified signals. Persist `states` (dict) across calls so each signal emits once.
- `execution/scanner/sink.py` - `emit_signals(signals, path)` -> append JSONL.

**Loop pattern (driver):**
1. Once at session start: `inplay = select_inplay(candidates, feed, params)`.
2. Every ~1 min: refresh the feed (re-pull recent bars), then `new = scan_once(inplay, feed, states, params)`; `emit_signals(new, "signals.jsonl")`.

**Edge cases / limits:**
- Signal-only: emits decision-support signals; execution stays manual (Phase 5 seam to the tv-mcp rails later).
- Spread is MODELED until a real L1 feed is wired.
- 500-bar feed cap is plenty for live (only recent bars are needed); the constraint matters for backtest, not live.
