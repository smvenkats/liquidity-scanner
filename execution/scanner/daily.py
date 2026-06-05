# execution/scanner/daily.py
"""Daily tiered signal feed: today's potential trades, split A (1h-aligned) / B (reversal).

Decision-support only — surfaces setups with sized tickets; it never places orders.
Run:  python -m execution.scanner.daily   (after `python -m execution.data.backfill`)
"""
from __future__ import annotations

from execution.scanner.tiers import tier_scan, position_size


def _ticket(s, risk_usd: float) -> str:
    qty = position_size(s.risk, risk_usd)
    notional = qty * s.entry_price
    return (f"  {s.symbol:<5} {s.direction.upper():<5} swept {s.level_type} @ "
            f"{s.reentry_time.strftime('%H:%M')} [{s.killzone}]\n"
            f"        entry {s.entry_price:.2f} | stop {s.stop_price:.2f} | target {s.target_price:.2f}"
            f" | RR {s.rr:.2f} | RS {s.rs_score * 100:+.2f}%\n"
            f"        size {qty} sh (~${notional:,.0f}) @ ${risk_usd:.0f} risk"
            f" | risk/sh {s.risk:.2f} | 1h-trend {s.htf_bias}")


def render(tier_a, tier_b, *, session, risk_usd: float) -> str:
    def block(title, sigs):
        if not sigs:
            return [f"{title}:", "  (none)"]
        rows = [_ticket(s, risk_usd) for s in sorted(sigs, key=lambda x: (x.symbol, x.reentry_time))]
        return [f"{title}:", *rows]

    lines = [f"Liquidity-sweep signals - session {session}  (risk ${risk_usd:.0f}/trade)", ""]
    lines += block(f"TIER A - aligned with 1h trend ({len(tier_a)})", tier_a)
    lines.append("")
    lines += block(f"TIER B - reversal watch / non-aligned 1h trend ({len(tier_b)})", tier_b)
    return "\n".join(lines)


if __name__ == "__main__":
    from execution.config import load_params
    from execution.backtest.store import BarStore
    from execution.data.env import load_dotenv

    load_dotenv()
    p = load_params()
    bench = p["data"]["benchmark"]
    store = BarStore(p["data"]["out_dir"])
    spy5 = store.bars(bench, "5m")
    if not spy5:
        raise SystemExit("No benchmark 5m data — run `python -m execution.data.backfill` first.")
    session = max(b.ts.date() for b in spy5)
    risk_usd = p["signals"]["risk_per_trade_usd"]
    a, b = tier_scan(p["data"]["universe"], store, p, benchmark=bench, as_of_date=session)
    print(render(a, b, session=session, risk_usd=risk_usd))
