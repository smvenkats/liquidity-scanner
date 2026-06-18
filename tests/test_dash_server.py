# tests/test_dash_server.py
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import dashboard.server as server

def _seed_static(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>dash</body></html>", encoding="utf-8")
    return static

def _seed_bars(tmp_path):
    rows = [{"ts": (datetime(2026, 6, 4, 13, 30) + timedelta(minutes=5 * i)).isoformat(),
             "o": 100 + i, "h": 100 + i, "l": 100 + i, "c": 100 + i, "v": 1} for i in range(10)]
    (tmp_path / "X_5m.json").write_text(json.dumps(rows))
    return tmp_path

def test_index_and_bars_and_backlog(tmp_path, monkeypatch):
    static = _seed_static(tmp_path)
    bars_dir = tmp_path / "data"; bars_dir.mkdir()
    _seed_bars(bars_dir)
    sig = tmp_path / "signals.jsonl"
    sig.write_text('{"symbol":"X","rr":3,"qualified":true}\n')

    monkeypatch.setattr(server, "STATIC", static)
    monkeypatch.setattr(server, "BARS_DIR", str(bars_dir))
    monkeypatch.setattr(server, "SIGNALS_PATH", sig)
    app = server.make_app()
    client = TestClient(app)

    assert "dash" in client.get("/").text                      # serves index.html
    ts = (datetime(2026, 6, 4, 13, 30) + timedelta(minutes=25)).isoformat()
    body = client.get(f"/bars?symbol=X&ts={ts}").json()
    assert body["symbol"] == "X" and len(body["bars"]) >= 1     # bars window

    with client.websocket_connect("/ws") as ws:                # backlog on connect
        msg = ws.receive_json()
        assert msg["type"] == "backlog" and msg["signals"][0]["symbol"] == "X"

def test_scan_status_endpoint(tmp_path, monkeypatch):
    static = _seed_static(tmp_path)
    bars_dir = tmp_path / "data"; bars_dir.mkdir()
    status = tmp_path / "scan_status.json"
    status.write_text(json.dumps({"raw_candidates": 8, "emitted": 4}))

    monkeypatch.setattr(server, "STATIC", static)
    monkeypatch.setattr(server, "BARS_DIR", str(bars_dir))
    monkeypatch.setattr(server, "SCAN_STATUS_PATH", status)
    app = server.make_app()
    client = TestClient(app)

    body = client.get("/scan-status").json()
    assert body["raw_candidates"] == 8
    assert body["emitted"] == 4

def test_ws_streams_new_signal(tmp_path, monkeypatch):
    static = _seed_static(tmp_path)
    bars_dir = tmp_path / "data"; bars_dir.mkdir()
    sig = tmp_path / "signals.jsonl"
    sig.write_text('{"symbol":"X","signal_id":"X-1","qualified":true}\n')
    monkeypatch.setattr(server, "STATIC", static)
    monkeypatch.setattr(server, "BARS_DIR", str(bars_dir))
    monkeypatch.setattr(server, "SIGNALS_PATH", sig)
    monkeypatch.setattr(server, "POLL_SECONDS", 0.05)
    app = server.make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "backlog"
            with sig.open("a") as f:
                f.write('{"symbol":"Y","signal_id":"Y-1","qualified":true}\n')
            msg = ws.receive_json()
            assert msg["type"] == "signal" and msg["signal"]["signal_id"] == "Y-1"
