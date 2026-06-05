import json
import pytest
from datetime import datetime, timezone
from execution.data import backfill as bf


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class FakeClient:
    """Stand-in for QuestradeClient. `responses` maps window-start-day -> candle list.
    `fail_days` raise QuestradeAPIError(status=fail_status) for that window's start day.
    `auth_fail` raises QuestradeAuthError on every call (a systemic failure)."""
    def __init__(self, responses, fail_days=(), fail_status=503, auth_fail=False):
        self.responses = responses
        self.fail_days = set(fail_days)
        self.fail_status = fail_status
        self.auth_fail = auth_fail

    def find_symbol_id(self, symbol):
        return 1

    def get_candles(self, symbol_id, start, end, interval="OneDay"):
        if self.auth_fail:
            raise bf.QuestradeAuthError("auth boom")
        if start.day in self.fail_days:
            raise bf.QuestradeAPIError("boom", status=self.fail_status)
        return self.responses.get(start.day, [])


def _candle(ts, c=1):
    return {"start": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1}


# ---------------------------------------------------------------------------
# fetch_series_questrade (pagination, guard, gap classification)
# ---------------------------------------------------------------------------

def test_fetch_series_paginates_and_stitches():
    client = FakeClient({1: [_candle("2026-01-01T00:00:00+00:00"),
                             _candle("2026-01-02T00:00:00+00:00")]})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"1d": {"interval": "OneDay", "window_days": 400}}}}
    rows, gaps = bf.fetch_series_questrade(client, "ABC", "1d", _dt(2026, 1, 1), _dt(2026, 1, 3), params)
    assert [r["ts"] for r in rows] == ["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]
    assert gaps == []


def test_fetch_series_guard_trips_over_500():
    big = [_candle(f"2026-01-01T00:{i:02d}:00+00:00") for i in range(500)]
    client = FakeClient({1: big})
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"1d": {"interval": "OneDay", "window_days": 400}}}}
    with pytest.raises(RuntimeError, match="500"):
        bf.fetch_series_questrade(client, "ABC", "1d", _dt(2026, 1, 1), _dt(2026, 1, 3), params)


def test_fetch_series_auth_failure_raises_unavailable():
    # Only a genuine auth failure is systemic.
    client = FakeClient({}, auth_fail=True)
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2}}}}
    with pytest.raises(bf.SeriesUnavailable):
        bf.fetch_series_questrade(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 10), params)


def test_fetch_series_old_window_400_is_gap_not_systemic():
    # The oldest window (day 1) 400s because it's beyond Questrade's intraday horizon;
    # a newer window (day 5) still has data. The series must survive, not fail wholesale.
    client = FakeClient({5: [_candle("2026-01-05T13:30:00+00:00")]}, fail_days={1}, fail_status=400)
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2}}}}
    rows, gaps = bf.fetch_series_questrade(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 7), params)
    assert len(rows) == 1 and rows[0]["ts"].startswith("2026-01-05")
    assert any(g[0].startswith("2026-01-01") for g in gaps)


def test_fetch_series_transient_window_failure_records_gap():
    client = FakeClient({1: [_candle("2026-01-01T13:30:00+00:00")],
                         5: [_candle("2026-01-05T13:30:00+00:00")]}, fail_days={3})  # 503 on day 3
    params = {"data": {"request_sleep_sec": 0,
                       "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2}}}}
    rows, gaps = bf.fetch_series_questrade(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 7), params)
    assert len(rows) == 2
    assert len(gaps) == 1 and gaps[0][0].startswith("2026-01-03")


# ---------------------------------------------------------------------------
# manifest + write_series
# ---------------------------------------------------------------------------

def test_write_series_writes_file_and_manifest(tmp_path):
    rows = [{"ts": "2026-01-01T13:30:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
            {"ts": "2026-01-02T13:30:00+00:00", "o": 2, "h": 2, "l": 2, "c": 2, "v": 2}]
    bf.write_series(tmp_path, "ABC", "1d", rows, source="questrade", gaps=[], status="ok")
    data = json.loads((tmp_path / "ABC_1d.json").read_text())
    assert len(data) == 2
    entry = json.loads((tmp_path / "manifest.json").read_text())["ABC_1d"]
    assert entry["source"] == "questrade"
    assert entry["covered_start"] == "2026-01-01T13:30:00+00:00"
    assert entry["covered_end"] == "2026-01-02T13:30:00+00:00"
    assert entry["row_count"] == 2 and entry["status"] == "ok"


def test_write_series_failed_writes_no_data_file(tmp_path):
    bf.write_series(tmp_path, "ABC", "5m", [], source="questrade", gaps=[], status="failed")
    assert not (tmp_path / "ABC_5m.json").exists()
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["ABC_5m"]["status"] == "failed" and man["ABC_5m"]["row_count"] == 0


# ---------------------------------------------------------------------------
# backfill_one (per-tf source order + resume)
# ---------------------------------------------------------------------------

def _params():
    return {"data": {"request_sleep_sec": 0, "out_dir": "ignored",
                     "windows": {"5m": {"interval": "FiveMinutes", "window_days": 2, "max_lookback_days": 100},
                                 "1h": {"interval": "OneHour", "window_days": 25, "max_lookback_days": 730},
                                 "1d": {"interval": "OneDay", "window_days": 400, "max_lookback_days": 800}}}}


def test_backfill_one_5m_no_data_marks_failed_no_file(tmp_path):
    # 5m is Questrade-only; with no data, status is 'failed' and NO file is written.
    client = FakeClient({}, fail_days={1})  # day-1 gaps, other windows empty -> zero rows
    status = bf.backfill_one(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 10), _params(), tmp_path)
    assert status == "failed"
    assert not (tmp_path / "ABC_5m.json").exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["ABC_5m"]["status"] == "failed"


def test_backfill_one_5m_partial_when_window_gaps(tmp_path):
    # Older windows 400 (gaps), newer windows have data -> 'partial', rows still written.
    client = FakeClient({5: [_candle("2026-01-05T13:30:00+00:00")]}, fail_days={1}, fail_status=400)
    status = bf.backfill_one(client, "ABC", "5m", _dt(2026, 1, 1), _dt(2026, 1, 7), _params(), tmp_path)
    assert status == "partial"
    man = json.loads((tmp_path / "manifest.json").read_text())["ABC_5m"]
    assert man["status"] == "partial" and man["source"] == "questrade" and len(man["gaps"]) >= 1
    assert (tmp_path / "ABC_5m.json").exists()


def test_backfill_one_1h_uses_yfinance_primary(tmp_path, monkeypatch):
    # 1h prefers yfinance (730d depth); the Questrade client must not be consulted.
    class NoQuestrade:
        def find_symbol_id(self, s): raise AssertionError("questrade must not be used for 1h primary")
        def get_candles(self, *a, **k): raise AssertionError("questrade must not be used for 1h primary")
    monkeypatch.setattr(bf, "_yf_fetch", lambda symbol, tf, start, end: [
        {"ts": "2026-01-02T10:00:00-05:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}])
    status = bf.backfill_one(NoQuestrade(), "ABC", "1h", _dt(2026, 1, 1), _dt(2026, 1, 10), _params(), tmp_path)
    assert status == "ok"
    man = json.loads((tmp_path / "manifest.json").read_text())["ABC_1h"]
    assert man["source"] == "yfinance" and man["row_count"] == 1


def test_backfill_one_1h_falls_back_to_questrade_when_yfinance_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(bf, "_yf_fetch", lambda *a, **k: [])  # yfinance yields nothing
    client = FakeClient({1: [_candle("2026-01-01T14:30:00+00:00")]})
    status = bf.backfill_one(client, "ABC", "1h", _dt(2026, 1, 1), _dt(2026, 1, 2), _params(), tmp_path)
    assert status == "ok"
    assert json.loads((tmp_path / "manifest.json").read_text())["ABC_1h"]["source"] == "questrade"


def test_backfill_one_1d_uses_questrade_primary(tmp_path, monkeypatch):
    client = FakeClient({1: [_candle("2026-01-01T00:00:00+00:00")]})
    monkeypatch.setattr(bf, "_yf_fetch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("yfinance not needed for 1d")))
    status = bf.backfill_one(client, "ABC", "1d", _dt(2026, 1, 1), _dt(2026, 1, 2), _params(), tmp_path)
    assert status == "ok"
    assert json.loads((tmp_path / "manifest.json").read_text())["ABC_1d"]["source"] == "questrade"


def test_backfill_one_skips_when_complete(tmp_path):
    bf.write_series(tmp_path, "ABC", "1d",
                    [{"ts": "2025-01-01T00:00:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
                    source="questrade", gaps=[], status="ok")

    class Boom:
        def find_symbol_id(self, s): raise AssertionError("should not be called")
        def get_candles(self, *a, **k): raise AssertionError("should not be called")

    status = bf.backfill_one(Boom(), "ABC", "1d", _dt(2025, 6, 1), _dt(2025, 6, 2),
                             _params(), tmp_path, force=False)
    assert status == "skipped"


# ---------------------------------------------------------------------------
# backfill top loop + isolation
# ---------------------------------------------------------------------------

def test_backfill_loops_and_summarizes(tmp_path):
    client = FakeClient({1: [_candle("2026-01-01T00:00:00+00:00")]})
    summary = bf.backfill(["ABC"], ["1d"], _dt(2026, 1, 1), _dt(2026, 1, 2),
                          _params(), out_dir=tmp_path, client=client)
    assert summary == {"ABC_1d": "ok"}
    assert (tmp_path / "ABC_1d.json").exists()


def test_backfill_continues_when_all_sources_fail(tmp_path, monkeypatch):
    # Both sources dead for every series -> each marked 'failed', the run never aborts.
    class BoomClient:
        def find_symbol_id(self, s): raise RuntimeError("network down")
        def get_candles(self, *a, **k): raise RuntimeError("network down")
    monkeypatch.setattr(bf, "_yf_fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("yf down")))
    summary = bf.backfill(["ABC", "DEF"], ["1d"], _dt(2026, 1, 1), _dt(2026, 1, 2),
                          _params(), out_dir=tmp_path, client=BoomClient())
    assert summary == {"ABC_1d": "failed", "DEF_1d": "failed"}


def test_backfill_outer_isolation_on_unexpected_error(tmp_path, monkeypatch):
    # If backfill_one itself raises unexpectedly, the loop records 'error:' and continues.
    monkeypatch.setattr(bf, "backfill_one",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = bf.backfill(["ABC", "DEF"], ["1d"], _dt(2026, 1, 1), _dt(2026, 1, 2),
                          _params(), out_dir=tmp_path, client=object())
    assert len(summary) == 2 and all(v.startswith("error:") for v in summary.values())
