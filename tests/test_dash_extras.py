import base64
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from dashboard.scheduler import is_market_hours, interval_seconds


def _utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_is_market_hours_weekday_rth():
    # 2026-06-04 is a Thursday; 14:00 UTC = 10:00 EDT -> within 09:30-16:00 ET
    assert is_market_hours(_utc(2026, 6, 4, 14, 0)) is True


def test_is_market_hours_offhours_and_weekend():
    assert is_market_hours(_utc(2026, 6, 4, 2, 0)) is False    # 22:00 ET prev day
    assert is_market_hours(_utc(2026, 6, 6, 14, 0)) is False   # Saturday


def test_interval_seconds_tighter_in_rth(monkeypatch):
    monkeypatch.setenv("SCAN_INTERVAL_MIN", "15")
    monkeypatch.setenv("SCAN_IDLE_MIN", "60")
    assert interval_seconds(_utc(2026, 6, 4, 14, 0)) == 15 * 60   # RTH
    assert interval_seconds(_utc(2026, 6, 6, 14, 0)) == 60 * 60   # weekend -> idle


def test_test_signal_endpoint_appends_and_requires_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("DASH_USER", "u")
    monkeypatch.setenv("DASH_PASSWORD", "p")
    monkeypatch.delenv("SCAN_ENABLED", raising=False)
    import dashboard.server as srv
    monkeypatch.setattr(srv, "SIGNALS_PATH", tmp_path / "s.jsonl")
    app = srv.make_app()
    h = {"Authorization": "Basic " + base64.b64encode(b"u:p").decode()}
    with TestClient(app) as c:
        assert c.post("/test-signal").status_code == 401           # no creds -> rejected
        r = c.post("/test-signal", headers=h)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert (tmp_path / "s.jsonl").exists()
