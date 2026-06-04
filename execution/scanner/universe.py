# execution/scanner/universe.py
from __future__ import annotations
from execution.levels import previous_session_levels
from execution.indicators import atr
from execution.backtest.features import adv_from_daily


def is_inplay(daily, bars5, params) -> bool:
    """Pre-filter: liquid enough AND (gapped OR sitting near a prior-day level)."""
    u = params["universe"]
    if len(daily) < 2 or not bars5:
        return False
    today = max(b.ts.date() for b in bars5)
    sess = [b for b in bars5 if b.ts.date() == today]
    if not sess:
        return False
    price = sess[-1].c
    prev_close = daily[-2].c if daily[-1].ts.date() >= today else daily[-1].c
    if price < u["min_price"] or adv_from_daily(daily) < u["min_adv_shares"]:
        return False
    gap = abs(sess[0].o - prev_close) / prev_close if prev_close else 0.0
    try:
        lvl = previous_session_levels(daily, today)
    except ValueError:
        return gap >= u["gap_pct"]
    pre = [b for b in bars5 if b.ts.date() < today]
    atr5 = atr(pre, params["detection"]["atr_len"]) if len(pre) >= params["detection"]["atr_len"] + 1 else 0.0
    band = u["near_level_atr"] * atr5
    near = abs(price - lvl.pdh) <= band or abs(price - lvl.pdl) <= band
    return gap >= u["gap_pct"] or near


def select_inplay(symbols, feed, params) -> list:
    picked = [s for s in symbols if is_inplay(feed.bars(s, "1d"), feed.bars(s, "5m"), params)]
    return picked[: params["universe"]["inplay_max"]]
