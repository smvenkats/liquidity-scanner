"""Read-only Questrade market-data client (ported from odte-vwap-scanner).

Handles Questrade OAuth and authorized market-data GETs (symbol lookup + candles).
Default HTTP transport is stdlib ``urllib``; if Questrade's Cloudflare layer blocks
it, the transport ladder falls back to ``curl_cffi`` (Chrome TLS impersonation) and
then ``cloudscraper`` when those optional packages are installed
(``QUESTRADE_HTTP_TRANSPORT`` forces a specific transport).

Auth model (the user supplies their own credentials):
  1. Generate a manual refresh token from a Questrade personal app and put it in
     ``.env`` as ``QUESTRADE_REFRESH_TOKEN``.
  2. This client redeems it for an access token + ``api_server`` URL.
  3. Questrade rotates the refresh token on every exchange (single-use), so the
     rotated token + access token are cached to a gitignored JSON file
     (``QUESTRADE_TOKEN_CACHE``, default ``.questrade_token.json`` at project root).
     Subsequent runs reuse the cached refresh token.

This module reads market data only (``read_md`` scope). It never trades.

NOTE: live calls require a Questrade market-data entitlement on the account.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Optional

TOKEN_URL = "https://login.questrade.com/oauth2/token"
# Questrade's endpoints sit behind Cloudflare, which 403s the default
# "Python-urllib/x" User-Agent (Cloudflare error 1010). A normal browser UA
# is required on every request.
_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _describe_http_error(code: int, url: str, body: str) -> str:
    msg = f"HTTP {code} for {url}: {body[:200]}"
    if code == 403 and "1010" in body:
        msg += " [Cloudflare error 1010 — the default User-Agent is banned; a browser UA is required]"
    return msg
DEFAULT_TOKEN_CACHE = Path(__file__).resolve().parents[2] / ".questrade_token.json"
_ACCESS_TOKEN_SKEW_SECONDS = 60  # refresh a little early to avoid edge-of-expiry 401s


class QuestradeAuthError(RuntimeError):
    """Raised when no usable refresh token is available or the exchange fails."""


class QuestradeAPIError(RuntimeError):
    """Raised on a non-2xx API response. Carries the HTTP status code."""

    def __init__(self, message: str, status: Optional[int] = None,
                 is_cloudflare: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.is_cloudflare = is_cloudflare


def _looks_like_cloudflare(text: str) -> bool:
    low = text.lower()
    return ("cloudflare" in low or "<!doctype html" in low or "just a moment" in low)


def _urllib_request_json(url: str, headers: Optional[dict] = None,
                         form: Optional[dict] = None) -> dict:
    """Stdlib transport: GET (or POST if ``form``) a URL and return parsed JSON.

    Raises ``QuestradeAPIError`` (with .status and .is_cloudflare) on failure.
    """
    headers = {**_DEFAULT_HEADERS, **(headers or {})}
    data = None
    method = "GET"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        is_cf = _looks_like_cloudflare(body) or (e.code == 403 and "1010" in body)
        raise QuestradeAPIError(_describe_http_error(e.code, url, body),
                                status=e.code, is_cloudflare=is_cf) from e
    except urllib.error.URLError as e:  # network down, DNS, etc.
        raise QuestradeAPIError(f"Network error for {url}: {e.reason}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 2xx but not JSON: almost always a Cloudflare interstitial/challenge page.
        is_cf = _looks_like_cloudflare(raw)
        hint = (" Looks like a Cloudflare challenge page, not Questrade's API."
                if is_cf else "")
        raise QuestradeAPIError(f"Non-JSON response (status {status}) from {url}.{hint}",
                                status=status, is_cloudflare=is_cf)


def _curl_cffi_available() -> bool:
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False


def _curl_cffi_request_json(url: str, headers: Optional[dict] = None,
                            form: Optional[dict] = None) -> dict:
    """Fallback transport using the optional ``curl_cffi`` package.

    curl_cffi impersonates a real Chrome TLS/JA3 fingerprint, which clears modern
    Cloudflare checks more often than cloudscraper. We pass only the caller's
    explicit headers (e.g. Authorization) and let curl_cffi own the UA/TLS profile.
    """
    try:
        from curl_cffi import requests as cffi
    except ImportError as e:
        raise QuestradeAPIError("curl_cffi is not installed. Run: pip install curl_cffi") from e
    try:
        if form is not None:
            resp = cffi.post(url, data=form, headers=headers or {}, impersonate="chrome", timeout=30)
        else:
            resp = cffi.get(url, headers=headers or {}, impersonate="chrome", timeout=30)
    except Exception as e:  # noqa: BLE001 — surface any curl_cffi/network failure
        raise QuestradeAPIError(f"curl_cffi request failed for {url}: {e}") from e
    text = resp.text
    if resp.status_code >= 400:
        is_cf = _looks_like_cloudflare(text) or (resp.status_code == 403 and "1010" in text)
        raise QuestradeAPIError(_describe_http_error(resp.status_code, url, text),
                                status=resp.status_code, is_cloudflare=is_cf)
    try:
        return resp.json()
    except Exception:
        is_cf = _looks_like_cloudflare(text)
        hint = " Cloudflare challenge page." if is_cf else ""
        raise QuestradeAPIError(f"Non-JSON response (status {resp.status_code}) from {url} "
                                f"via curl_cffi.{hint}", status=resp.status_code, is_cloudflare=is_cf)


def _cloudscraper_available() -> bool:
    try:
        import cloudscraper  # noqa: F401
        return True
    except Exception:
        return False


def _cloudscraper_request_json(url: str, headers: Optional[dict] = None,
                               form: Optional[dict] = None) -> dict:
    """Fallback transport using the optional ``cloudscraper`` package.

    Note: we pass through only the caller's explicit headers (e.g. Authorization),
    NOT our browser User-Agent — cloudscraper sets a UA matching the TLS cipher
    suite it uses to solve the challenge, and overriding it breaks the bypass.
    """
    try:
        import cloudscraper
    except ImportError as e:
        raise QuestradeAPIError(
            "cloudscraper is not installed. Run: pip install cloudscraper") from e
    scraper = cloudscraper.create_scraper()
    try:
        if form is not None:
            resp = scraper.post(url, data=form, headers=headers or {}, timeout=30)
        else:
            resp = scraper.get(url, headers=headers or {}, timeout=30)
    except Exception as e:  # noqa: BLE001 — surface any cloudscraper/network failure
        raise QuestradeAPIError(f"cloudscraper request failed for {url}: {e}") from e
    if resp.status_code >= 400:
        raise QuestradeAPIError(_describe_http_error(resp.status_code, url, resp.text),
                                status=resp.status_code)
    try:
        return resp.json()
    except ValueError:
        raise QuestradeAPIError(
            f"Non-JSON response (status {resp.status_code}) from {url} via cloudscraper.",
            status=resp.status_code)


def _http_request_json(url: str, headers: Optional[dict] = None,
                       form: Optional[dict] = None) -> dict:
    """Transport dispatcher. QUESTRADE_HTTP_TRANSPORT selects behaviour:

      * 'auto' (default) — try urllib; on a Cloudflare block, fall back to the
        stronger bypasses in order (curl_cffi, then cloudscraper) if installed,
        else raise with an install hint.
      * 'urllib'         — stdlib only, no fallback.
      * 'curl_cffi'      — force the curl_cffi transport (Chrome TLS impersonation).
      * 'cloudscraper'   — force the cloudscraper transport.

    Isolated at module level so tests can monkeypatch it directly.
    """
    transport = (os.environ.get("QUESTRADE_HTTP_TRANSPORT") or "auto").lower()
    if transport == "curl_cffi":
        return _curl_cffi_request_json(url, headers, form)
    if transport == "cloudscraper":
        return _cloudscraper_request_json(url, headers, form)
    try:
        return _urllib_request_json(url, headers, form)
    except QuestradeAPIError as e:
        if transport == "auto" and getattr(e, "is_cloudflare", False):
            # Try the stronger bypasses in order of effectiveness; return the first
            # that yields JSON, else raise the last failure with an install hint.
            last = e
            for available, fn in ((_curl_cffi_available, _curl_cffi_request_json),
                                  (_cloudscraper_available, _cloudscraper_request_json)):
                if available():
                    try:
                        return fn(url, headers, form)
                    except QuestradeAPIError as e2:
                        last = e2
            raise QuestradeAPIError(
                str(last) + " [bypass failed/unavailable; pip install curl_cffi for the best odds]",
                status=getattr(last, "status", None), is_cloudflare=True) from last
        raise


class QuestradeClient:
    """Handles Questrade OAuth + authorized market-data GETs with token caching."""

    def __init__(self, refresh_token: Optional[str] = None,
                 token_cache_path: Optional[str | Path] = None) -> None:
        self._env_refresh_token = refresh_token or os.environ.get("QUESTRADE_REFRESH_TOKEN")
        self._cache_path = Path(token_cache_path
                                or os.environ.get("QUESTRADE_TOKEN_CACHE")
                                or DEFAULT_TOKEN_CACHE)
        self._access_token: Optional[str] = None
        self._api_server: Optional[str] = None
        self._expires_at: float = 0.0
        self._symbol_id_cache: dict[str, int] = {}
        self._load_cache()

    # -- token cache --------------------------------------------------------

    def _load_cache(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._access_token = data.get("access_token")
        self._api_server = data.get("api_server")
        self._expires_at = float(data.get("expires_at", 0.0))
        # A cached (rotated) refresh token always supersedes the .env one.
        if data.get("refresh_token"):
            self._cached_refresh_token: Optional[str] = data["refresh_token"]
        else:
            self._cached_refresh_token = None

    def _save_cache(self, refresh_token: str) -> None:
        payload = {
            "access_token": self._access_token,
            "api_server": self._api_server,
            "expires_at": self._expires_at,
            "refresh_token": refresh_token,
        }
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._cached_refresh_token = refresh_token

    # -- auth ---------------------------------------------------------------

    def _current_refresh_token(self) -> str:
        token = getattr(self, "_cached_refresh_token", None) or self._env_refresh_token
        if not token:
            raise QuestradeAuthError(
                "No Questrade refresh token. Set QUESTRADE_REFRESH_TOKEN in .env "
                "(generate one in the Questrade API centre -> personal apps).")
        return token

    def _exchange_refresh_token(self, refresh_token: str) -> dict:
        return _http_request_json(TOKEN_URL, form={
            "grant_type": "refresh_token", "refresh_token": refresh_token})

    def _refresh_access_token(self) -> None:
        """Exchange the refresh token for an access token; persist the rotation."""
        rt = self._current_refresh_token()
        try:
            data = self._exchange_refresh_token(rt)
        except QuestradeAPIError as e:
            if e.status == 400:
                env_rt = self._env_refresh_token
                if (getattr(self, "_cached_refresh_token", None)
                        and env_rt and env_rt != rt):
                    try:
                        data = self._exchange_refresh_token(env_rt)
                    except QuestradeAPIError as env_e:
                        raise QuestradeAuthError(
                            f"Token exchange failed ({env_e}). The refresh token is invalid, already "
                            "used, or expired — Questrade tokens are single-use. Regenerate one in "
                            "the API centre and update QUESTRADE_REFRESH_TOKEN.") from env_e
                    else:
                        print("[questrade] cached refresh token was rejected; recovered with "
                              "QUESTRADE_REFRESH_TOKEN and updated token cache", flush=True)
                        self._access_token = data["access_token"]
                        self._api_server = data["api_server"].rstrip("/")
                        self._expires_at = time.time() + float(data.get("expires_in", 1800))
                        self._save_cache(data["refresh_token"])
                        return
                raise QuestradeAuthError(
                    f"Token exchange failed ({e}). The refresh token is invalid, already "
                    "used, or expired — Questrade tokens are single-use. Regenerate one in "
                    "the API centre and update QUESTRADE_REFRESH_TOKEN.") from e
            if e.status == 403 and "1010" in str(e):
                raise QuestradeAuthError(
                    f"Token exchange blocked by Cloudflare (error 1010), not a token problem "
                    f"({e}). The request needs a browser User-Agent header.") from e
            raise QuestradeAuthError(
                f"Token exchange failed ({e}). This may be a Cloudflare block, network issue, "
                "or entitlement problem rather than a bad token.") from e
        self._access_token = data["access_token"]
        # api_server SOMETIMES includes the /v1 segment and sometimes omits it;
        # we normalize it when building URLs (see _build_url). Trim trailing slash.
        self._api_server = data["api_server"].rstrip("/")
        self._expires_at = time.time() + float(data.get("expires_in", 1800))
        self._save_cache(data["refresh_token"])

    def _ensure_access(self) -> tuple[str, str]:
        """Return a valid (access_token, api_server), refreshing if needed."""
        if (self._access_token and self._api_server
                and time.time() < self._expires_at - _ACCESS_TOKEN_SKEW_SECONDS):
            return self._access_token, self._api_server
        self._refresh_access_token()
        return self._access_token, self._api_server  # type: ignore[return-value]

    @staticmethod
    def _build_url(api_server: str, path: str, params: Optional[dict]) -> str:
        """Join api_server + path, guaranteeing exactly one ``/v1`` version segment.

        Questrade's api_server sometimes includes ``/v1`` and sometimes omits it;
        relying on it caused 404 'Invalid endpoint'. Normalize so the version is
        always present and never duplicated.
        """
        base = api_server.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        url = f"{base}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return url

    def _authorized_get(self, path: str, params: Optional[dict] = None) -> dict:
        """Authorized GET against ``{api_server}/v1{path}``; one refresh-retry on 401."""
        access, api_server = self._ensure_access()
        try:
            return _http_request_json(self._build_url(api_server, path, params),
                                      headers={"Authorization": f"Bearer {access}"})
        except QuestradeAPIError as e:
            if e.status == 401:  # access token rejected — force one refresh + retry
                self._expires_at = 0.0
                access, api_server = self._ensure_access()
                return _http_request_json(self._build_url(api_server, path, params),
                                          headers={"Authorization": f"Bearer {access}"})
            raise

    # -- market data --------------------------------------------------------

    def find_symbol_id(self, symbol: str) -> int:
        """Resolve a ticker to its Questrade internal symbolId (exact match)."""
        symbol = symbol.upper()
        if symbol in self._symbol_id_cache:
            return self._symbol_id_cache[symbol]
        data = self._authorized_get("/symbols/search", {"prefix": symbol})
        for s in data.get("symbols", []):
            if s.get("symbol", "").upper() == symbol:
                self._symbol_id_cache[symbol] = int(s["symbolId"])
                return self._symbol_id_cache[symbol]
        raise QuestradeAPIError(f"No exact Questrade symbol match for {symbol!r}")

    def get_candles(self, symbol_id: int, start: datetime, end: datetime,
                    interval: str = "OneMinute") -> list[dict]:
        """Fetch raw candle dicts for [start, end] at the given interval."""
        return self._authorized_get(
            f"/markets/candles/{symbol_id}",
            {"startTime": start.isoformat(), "endTime": end.isoformat(),
             "interval": interval}).get("candles", [])
