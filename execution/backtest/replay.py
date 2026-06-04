from __future__ import annotations
from dataclasses import replace
from execution.detect import SweepCandidate


def find_all_sweeps(bars, level_price, detect_fn, *, pen_min, max_reentry_bars,
                    **kw) -> list[SweepCandidate]:
    """Repeatedly scan a session, collecting every sweep (every-sweep re-arm).

    After each hit, advance past its re-entry bar. Indices on returned candidates
    are rebuilt to be absolute (relative to `bars`); timestamps are already absolute.
    """
    out: list[SweepCandidate] = []
    start = 0
    while start < len(bars):
        c = detect_fn(bars[start:], level_price, pen_min=pen_min,
                      max_reentry_bars=max_reentry_bars, **kw)
        if c is None:
            break
        out.append(replace(c, sweep_index=start + c.sweep_index,
                           reentry_index=start + c.reentry_index))
        start = start + c.reentry_index + 1
    return out
