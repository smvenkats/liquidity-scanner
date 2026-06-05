import base64
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from dashboard.auth import check_basic, require_auth


def _hdr(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


def test_check_basic_open_when_unset(monkeypatch):
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASSWORD", raising=False)
    assert check_basic(None) is True            # auth disabled (local dev) when not configured
    assert check_basic("Basic anything") is True


def test_check_basic_validates_when_set(monkeypatch):
    monkeypatch.setenv("DASH_USER", "fam")
    monkeypatch.setenv("DASH_PASSWORD", "secret")
    assert check_basic(_hdr("fam", "secret")) is True
    assert check_basic(_hdr("fam", "wrong")) is False
    assert check_basic(_hdr("other", "secret")) is False
    assert check_basic(None) is False
    assert check_basic("Basic !!!not-base64") is False
    assert check_basic("Bearer xyz") is False


def test_require_auth_dependency_enforces_401(monkeypatch):
    monkeypatch.setenv("DASH_USER", "fam")
    monkeypatch.setenv("DASH_PASSWORD", "secret")
    app = FastAPI()

    @app.get("/p", dependencies=[Depends(require_auth)])
    def p():
        return {"ok": True}

    c = TestClient(app)
    r = c.get("/p")
    assert r.status_code == 401 and "Basic" in r.headers.get("www-authenticate", "")
    assert c.get("/p", headers={"Authorization": _hdr("fam", "secret")}).status_code == 200


def test_make_app_refuses_without_auth_on_railway(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASSWORD", raising=False)
    from dashboard.server import make_app
    with pytest.raises(RuntimeError, match="without auth"):
        make_app()


def test_make_app_ok_on_railway_with_auth(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("DASH_USER", "fam")
    monkeypatch.setenv("DASH_PASSWORD", "x")
    from dashboard.server import make_app
    assert make_app() is not None
