# execution/levels.py
from __future__ import annotations
from datetime import date
from execution.models import Bar, Level


def previous_session_levels(daily_bars: list[Bar], session_date: date) -> Level:
    """PDH/PDL from the most recent COMPLETED day strictly before session_date.

    The forming session's own bar can never contribute to its level — this is the
    lookahead-bias lockdown on the Python side.
    """
    prior = [b for b in daily_bars if b.ts.date() < session_date]
    if not prior:
        raise ValueError(f"no daily bar before {session_date}")
    b = max(prior, key=lambda x: x.ts)
    return Level(pdh=b.h, pdl=b.l, source_date=b.ts.date())
