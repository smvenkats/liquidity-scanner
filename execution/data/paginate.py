# execution/data/paginate.py
from __future__ import annotations
from datetime import datetime, timedelta

_INTERVALS = {"5m": "FiveMinutes", "1h": "OneHour", "1d": "OneDay"}


def interval_for_tf(tf: str) -> str:
    try:
        return _INTERVALS[tf]
    except KeyError:
        raise ValueError(f"unsupported timeframe: {tf!r}")


def iter_windows(start: datetime, end: datetime,
                 window_days: int) -> list[tuple[datetime, datetime]]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    out: list[tuple[datetime, datetime]] = []
    cur = start
    span = timedelta(days=window_days)
    while cur < end:
        nxt = min(cur + span, end)
        out.append((cur, nxt))
        cur = nxt
    return out


def stitch(window_results: list[list[dict]], *, key: str = "ts") -> list[dict]:
    """Flatten paginated windows into one series: dedup by `key`, sort ascending."""
    seen: dict[str, dict] = {}
    for rows in window_results:
        for r in rows:
            seen[r[key]] = r  # identical at boundaries; last write wins
    return sorted(seen.values(), key=lambda r: r[key])
