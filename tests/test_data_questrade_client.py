import json
import pytest
from execution.data import questrade_client as qc


def test_build_url_inserts_single_v1():
    u = qc.QuestradeClient._build_url("https://api01.iq.questrade.com", "/markets/candles/9", None)
    assert u == "https://api01.iq.questrade.com/v1/markets/candles/9"
    u2 = qc.QuestradeClient._build_url("https://api01.iq.questrade.com/v1", "/x", {"a": 1})
    assert u2 == "https://api01.iq.questrade.com/v1/x?a=1"


def test_cached_refresh_token_supersedes_env(tmp_path):
    cache = tmp_path / "tok.json"
    cache.write_text(json.dumps({"refresh_token": "ROTATED", "access_token": "A",
                                 "api_server": "https://s", "expires_at": 0.0}))
    client = qc.QuestradeClient(refresh_token="ENV_SEED", token_cache_path=cache)
    assert client._current_refresh_token() == "ROTATED"


def test_save_cache_creates_parent_directory(tmp_path):
    cache = tmp_path / "data" / ".questrade_token.json"
    client = qc.QuestradeClient(refresh_token="ENV_SEED", token_cache_path=cache)
    client._access_token = "A"
    client._api_server = "https://s"
    client._expires_at = 123.0

    client._save_cache("ROTATED")

    data = json.loads(cache.read_text())
    assert data["refresh_token"] == "ROTATED"
    assert client._current_refresh_token() == "ROTATED"


def test_get_candles_parses_list(monkeypatch):
    client = qc.QuestradeClient(refresh_token="x", token_cache_path="/nonexistent.json")
    monkeypatch.setattr(client, "_authorized_get",
                        lambda path, params=None: {"candles": [{"start": "t", "open": 1}]})
    from datetime import datetime, timezone
    out = client.get_candles(9, datetime(2026, 1, 1, tzinfo=timezone.utc),
                             datetime(2026, 1, 2, tzinfo=timezone.utc), interval="FiveMinutes")
    assert out == [{"start": "t", "open": 1}]


def test_transport_dispatch_forces_curl_cffi(monkeypatch):
    monkeypatch.setenv("QUESTRADE_HTTP_TRANSPORT", "curl_cffi")
    monkeypatch.setattr(qc, "_curl_cffi_request_json", lambda *a, **k: {"via": "curl_cffi"})
    assert qc._http_request_json("https://x") == {"via": "curl_cffi"}
