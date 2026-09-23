"""Google Search Console integration: OAuth + Search Analytics client.

Real Google APIs, no invented data:
- OAuth 2.0 (webmasters.readonly): auth URL → code exchange → refreshable
  tokens, stored encrypted in gsc_connections.
- sites.list → property picker; searchanalytics.query with date/country/
  device dimensions, paginated, upserted into gsc_query_data/gsc_page_data.

Token refresh and API calls raise ProviderError subclasses (auth vs
retryable) so jobs fail honestly with actionable messages.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
from jose import jwt

from app.config import get_settings
from app.providers.base import ProviderAuthError, ProviderError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
TIMEOUT = 30.0


def utcnow() -> datetime:
    return datetime.now(UTC)


def oauth_config() -> dict:
    s = get_settings()
    cid = getattr(s, "google_client_id", None)
    secret = getattr(s, "google_client_secret", None)
    redirect = getattr(s, "google_redirect_uri", None) or \
        "http://localhost:8000/api/v1/gsc/oauth/callback"
    if not cid or not secret:
        raise ProviderError(
            "Google OAuth not configured — set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET",
            code="PROVIDER_CONFIG")
    return {"client_id": cid, "client_secret": secret, "redirect_uri": redirect}


def make_state_token(organization_id: str, project_id: str | None,
                     user_id: str) -> str:
    s = get_settings()
    exp = utcnow() + timedelta(minutes=15)
    return jwt.encode({"purpose": "gsc", "org": organization_id,
                       "project": project_id, "user": user_id, "exp": exp},
                      s.jwt_secret, algorithm=s.jwt_algorithm)


def parse_state_token(token: str) -> dict:
    from jose import JWTError
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError as exc:
        raise ProviderError(f"invalid OAuth state: {exc}") from exc
    if payload.get("purpose") != "gsc":
        raise ProviderError("invalid OAuth state purpose")
    return payload


def authorization_url(organization_id: str, project_id: str | None,
                      user_id: str) -> str:
    cfg = oauth_config()
    from urllib.parse import urlencode
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": make_state_token(organization_id, project_id, user_id),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Code → {access_token, refresh_token, expires_at, scopes, account?}."""
    cfg = oauth_config()
    try:
        resp = httpx.post(TOKEN_URL, data={
            "code": code, "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": cfg["redirect_uri"], "grant_type": "authorization_code",
        }, timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
            httpx.PoolTimeout) as exc:
        raise ProviderError(f"Google token exchange failed: {exc}",
                            code="PROVIDER_TIMEOUT", retryable=True) from exc
    if resp.status_code in (400, 401):
        raise ProviderAuthError(f"Google rejected the OAuth code: {resp.text[:200]}")
    data = resp.json()
    if "access_token" not in data:
        raise ProviderError(f"Google token response invalid: {str(data)[:200]}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": utcnow() + timedelta(seconds=int(data.get("expires_in", 3600))),
        "scopes": data.get("scope", ""),
    }


def refresh_access_token(refresh_token: str) -> dict:
    cfg = oauth_config()
    try:
        resp = httpx.post(TOKEN_URL, data={
            "refresh_token": refresh_token, "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"], "grant_type": "refresh_token",
        }, timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
            httpx.PoolTimeout) as exc:
        raise ProviderError(f"Google refresh failed: {exc}",
                            code="PROVIDER_TIMEOUT", retryable=True) from exc
    if resp.status_code in (400, 401):
        raise ProviderAuthError("Google refresh token invalid — reconnect Search Console")
    data = resp.json()
    return {"access_token": data["access_token"],
            "expires_at": utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)))}


class SearchConsoleClient:
    """Authenticated SC API client with auto-refresh (refresh callback injected)."""

    def __init__(self, access_token: str, expires_at: datetime | None,
                 refresh_token: str, on_refresh=None):
        self.access_token = access_token
        self.expires_at = expires_at
        self.refresh_token = refresh_token
        self.on_refresh = on_refresh

    def _headers(self) -> dict:
        exp = self.expires_at
        if exp is not None:
            now = utcnow()
            aware = exp if exp.tzinfo else exp.replace(tzinfo=UTC)
            if aware - now < timedelta(minutes=5):
                data = refresh_access_token(self.refresh_token)
                self.access_token = data["access_token"]
                self.expires_at = data["expires_at"]
                if self.on_refresh:
                    self.on_refresh(data)
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, url: str, retries: int = 3):
        last = None
        for attempt in range(retries):
            try:
                resp = httpx.get(url, headers=self._headers(), timeout=TIMEOUT)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                    httpx.PoolTimeout) as exc:
                last = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 401:
                raise ProviderAuthError("Google access denied — reconnect Search Console")
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ProviderError(f"Google API {resp.status_code}", retryable=True)
                time.sleep(2 ** attempt * 5)
                continue
            resp.raise_for_status()
            return resp.json()
        raise ProviderError(f"Google API failed: {last}", code="PROVIDER_UPSTREAM",
                            retryable=True)

    def _post(self, url: str, payload: dict, retries: int = 3):
        last = None
        for attempt in range(retries):
            try:
                resp = httpx.post(url, headers=self._headers(), json=payload,
                                  timeout=TIMEOUT)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                    httpx.PoolTimeout) as exc:
                last = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 401:
                raise ProviderAuthError("Google access denied — reconnect Search Console")
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ProviderError(f"Google API {resp.status_code}", retryable=True)
                time.sleep(2 ** attempt * 5)
                continue
            resp.raise_for_status()
            return resp.json()
        raise ProviderError(f"Google API failed: {last}", code="PROVIDER_UPSTREAM",
                            retryable=True)

    def list_properties(self) -> list[dict]:
        data = self._get(SITES_URL)
        return [{"site_url": s.get("siteUrl", ""),
                 "property_type": "DOMAIN" if s.get("siteUrl", "").startswith("sc-domain:")
                 else "URL_PREFIX"}
                for s in (data.get("siteEntry") or []) if s.get("siteUrl")]

    def query_analytics(self, site_url: str, start_date: str, end_date: str,
                        dimensions: list[str], row_limit: int = 25000,
                        start_row: int = 0) -> list[dict]:
        """One page of searchAnalytics rows. Caller paginates via start_row."""
        import urllib.parse
        data = self._post(
            f"{SITES_URL}/{urllib.parse.quote(site_url, safe='')}/searchAnalytics/query",
            {"startDate": start_date, "endDate": end_date,
             "dimensions": dimensions, "rowLimit": row_limit,
             "startRow": start_row})
        return data.get("rows") or []
