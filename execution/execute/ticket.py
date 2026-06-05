# execution/execute/ticket.py
"""Deterministic Signal -> order ticket. Pure: no broker, no I/O, places nothing.

Guardrails FLAG (never silently clamp) when a cap would bind — clamping would change
the user's risk profile behind their back. The reported qty is always the risk-true size.
"""
from __future__ import annotations
from dataclasses import dataclass

from execution.scanner.tiers import position_size


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
    est_notional: float
    warnings: list


def build_ticket(signal, *, risk_usd: float, max_notional: float, max_qty: int) -> OrderTicket:
    side = "buy" if signal.direction == "long" else "sell"
    qty = position_size(signal.risk, risk_usd)
    limit = signal.entry_price
    notional = qty * limit
    warnings: list[str] = []
    if qty < 1:
        warnings.append("risk budget too small for one share (stop too wide)")
    if notional > max_notional:
        warnings.append(f"est notional ${notional:,.0f} exceeds max ${max_notional:,.0f}")
    if qty > max_qty:
        warnings.append(f"qty {qty} exceeds max {max_qty}")
    return OrderTicket(
        symbol=signal.symbol, side=side, qty=qty, order_type="limit",
        limit_price=limit, stop_price=signal.stop_price, target_price=signal.target_price,
        risk_per_share=signal.risk, est_notional=notional, warnings=warnings)
