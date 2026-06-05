import pytest
from execution.data.paginate import interval_for_tf

def test_interval_for_tf_maps_known():
    assert interval_for_tf("5m") == "FiveMinutes"
    assert interval_for_tf("1h") == "OneHour"
    assert interval_for_tf("1d") == "OneDay"

def test_interval_for_tf_rejects_unknown():
    with pytest.raises(ValueError):
        interval_for_tf("3m")


from datetime import datetime, timezone
from execution.data.paginate import iter_windows

def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)

def test_iter_windows_splits_range():
    w = iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 6), window_days=2)
    assert w == [(_dt(2026, 1, 1), _dt(2026, 1, 3)),
                 (_dt(2026, 1, 3), _dt(2026, 1, 5)),
                 (_dt(2026, 1, 5), _dt(2026, 1, 6))]

def test_iter_windows_range_smaller_than_window():
    w = iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 2), window_days=400)
    assert w == [(_dt(2026, 1, 1), _dt(2026, 1, 2))]

def test_iter_windows_empty_when_start_ge_end():
    assert iter_windows(_dt(2026, 1, 2), _dt(2026, 1, 1), window_days=2) == []

def test_iter_windows_rejects_nonpositive_window():
    with pytest.raises(ValueError):
        iter_windows(_dt(2026, 1, 1), _dt(2026, 1, 2), window_days=0)


from execution.data.paginate import stitch

def _row(ts, c):
    return {"ts": ts, "o": c, "h": c, "l": c, "c": c, "v": 1}

def test_stitch_dedups_by_ts_and_sorts():
    a = [_row("2026-01-02T13:30:00+00:00", 1), _row("2026-01-02T13:35:00+00:00", 2)]
    b = [_row("2026-01-02T13:35:00+00:00", 2), _row("2026-01-02T13:40:00+00:00", 3)]
    out = stitch([a, b])
    assert [r["ts"] for r in out] == [
        "2026-01-02T13:30:00+00:00",
        "2026-01-02T13:35:00+00:00",
        "2026-01-02T13:40:00+00:00",
    ]
    assert len(out) == 3

def test_stitch_handles_empty():
    assert stitch([[], []]) == []
