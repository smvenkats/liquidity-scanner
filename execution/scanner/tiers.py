# execution/scanner/tiers.py
"""Tiered live-signal feed.

The 1h-trend gate's value (help vs hurt) cannot be settled on the available data,
so rather than discard counter-trend setups we CLASSIFY them:

  Tier A (aligned):  passes RS + liquidity + R:R AND the 1h-trend gate.
  Tier B (reversal): passes RS + liquidity + R:R but opposes the 1h trend.

Both are surfaced, clearly labelled. This is an additive layer over the existing
scanner — it runs scan_once with the gate on (A) and off (A∪B) and diffs by
signal_id — so the reviewed detection core is untouched. Decision-support only.
"""
from __future__ import annotations

from datetime import timedelta

from execution.scanner.engine import scan_once
from execution.trend import htf_trend


def split_tiers(aligned, all_core_passing):
    """Given the gate-ON signals (aligned) and the gate-OFF signals (all core-passing,
    a superset), return (tier_A, tier_B) where B is the counter-trend remainder."""
    aligned_ids = {s.signal_id for s in aligned}
    tier_a = list(aligned)
    tier_b = [s for s in all_core_passing if s.signal_id not in aligned_ids]
    return tier_a, tier_b


def position_size(risk_per_share: float, risk_usd: float) -> int:
    """Whole-share size for a fixed dollar risk: floor(risk_usd / per-share stop)."""
    if risk_per_share <= 0 or risk_usd <= 0:
        return 0
    return int(risk_usd / risk_per_share)


def annotate_trend(signals, feed, params):
    """Set each signal's htf_bias to its ACTUAL 1h trend at entry. Tier-B signals come
    from the gate-OFF run (trend never computed -> htf_bias None), so without this the
    feed can't distinguish a true reversal (1h opposes) from a trend-unconfirmed setup
    (1h flat / insufficient data). Mutates and returns the signals."""
    trd = params["trend"]
    for s in signals:
        closed = [b.c for b in feed.bars(s.symbol, "1h") if b.ts + timedelta(hours=1) <= s.reentry_time]
        s.htf_bias = htf_trend(closed, ema_len=trd["htf_ema_len"], require_slope=trd["htf_require_slope"])
    return signals


def dedupe_setups(signals):
    """Collapse repeat reclaims of the same level to ONE setup per
    (symbol, level_type, direction): the earliest trigger (the actionable entry).
    The 'every_sweep' re-arm fires on each reentry bar; a feed wants one alert."""
    best: dict = {}
    for s in signals:
        key = (s.symbol, s.level_type, s.direction)
        if key not in best or s.reentry_time < best[key].reentry_time:
            best[key] = s
    return list(best.values())


def tier_scan(universe, feed, params, *, benchmark="SPY", as_of_date=None):
    """Run the scanner twice (gate on/off) and return (tier_A, tier_B) for the session."""
    aligned = scan_once(universe, feed, {}, params=params, benchmark=benchmark,
                        trend_gate=True, mode="live", as_of_date=as_of_date)
    all_core = scan_once(universe, feed, {}, params=params, benchmark=benchmark,
                         trend_gate=False, mode="live", as_of_date=as_of_date)
    tier_a, tier_b = split_tiers(aligned, all_core)
    # Tier A already carries its real 1h trend (gate was on); annotate B so the feed
    # shows whether each is a true reversal (1h opposes) or trend-unconfirmed (flat).
    return dedupe_setups(tier_a), annotate_trend(dedupe_setups(tier_b), feed, params)
