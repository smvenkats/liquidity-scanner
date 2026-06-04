# tests/test_levels.py
from datetime import datetime, date
import pytest
from execution.models import Bar
from execution.levels import previous_session_levels

def _daily(d, h, l):
    return Bar(ts=datetime.fromisoformat(d + "T00:00:00+00:00"),
               o=h, h=h, l=l, c=l, v=1)

def test_uses_prior_completed_day_only():
    bars = [_daily("2026-06-01", 100, 90),
            _daily("2026-06-02", 110, 95),
            _daily("2026-06-03", 999, 1)]   # the forming session — MUST be ignored
    lvl = previous_session_levels(bars, date(2026, 6, 3))
    assert lvl.pdh == 110 and lvl.pdl == 95
    assert lvl.source_date == date(2026, 6, 2)

def test_raises_when_no_prior_day():
    bars = [_daily("2026-06-03", 100, 90)]
    with pytest.raises(ValueError):
        previous_session_levels(bars, date(2026, 6, 3))
