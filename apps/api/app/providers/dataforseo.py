"""DataForSEO provider — SERP + keyword-data live endpoints.

Docs: https://docs.dataforseo.com/v3/serp/google/organic/live_advanced/
      https://docs.dataforseo.com/v3/keywords_data/google_ads/search_volume/live/
      https://docs.dataforseo.com/v3/keywords_data/google_ads/keywords_for_keywords/live/

Every number returned comes from the vendor response. Nothing is estimated
or invented here; difficulty/opportunity are computed in app/keywords.py
from this data and labeled as platform estimates.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from app.providers.base import (
    KeywordMetrics,
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    SerpResponse,
    SerpResultItem,
)

API_BASE = "https://api.dataforseo.com"
TIMEOUT = 90.0
MAX_RETRIES = 3

# DataForSEO location_code per country (country targeting). Callers may pass
# an explicit location_code to override (city/region targeting).
LOCATION_CODES = {
    "US": 2840, "GB": 2826, "IN": 2356, "CA": 2124, "AU": 2036,
    "DE": 2276, "FR": 2250, "ES": 2724, "IT": 2380, "NL": 2528,
    "BR": 2076, "MX": 2344, "JP": 2392, "SE": 2752, "PL": 2616,
}

DEVICE_MAP = {"DESKTOP": "desktop", "MOBILE": "mobile"}

# SERP item types that carry a rankable URL.
ORGANIC_TYPES = {"organic"}
PAID_TYPES = {"paid"}
FEATURE_TYPES = {
    "featured_snippet", "people_also_ask", "local_pack", "video", "images",
    "news", "shopping", "knowledge_graph", "knowledge_graph_shopping",
    "top_stories", "questions_and_answers", "related_searches", "hotels_pack",
    "jobs", "events", "maps", "tweets", "found_on_web",
}


def location_code_for(country: str, explicit: int | None = None) -> int:
    if explicit:
        return explicit
    code = LOCATION_CODES.get((country or "US").upper())
    if code is None:
        raise ProviderError(
            f"no location mapping for country {country!r} — pass location_code explicitly",
            code="PROVIDER_CONFIG")
    return code


def _post(path: str, payload: list[dict], login: str, password: str) -> dict:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = httpx.post(f"{API_BASE}{path}", json=payload,
                              auth=(login, password), timeout=TIMEOUT)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.PoolTimeout) as exc:
            last = ProviderError(f"DataForSEO network error: {exc}",
                                 code="PROVIDER_TIMEOUT", retryable=True)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 401:
            raise ProviderAuthError("DataForSEO rejected the login/password")
        if resp.status_code == 429:
            last = ProviderError("DataForSEO rate limited", code="PROVIDER_RATE",
                                 retryable=True)
            time.sleep(2 ** attempt * 5)
            continue
        if resp.status_code >= 500:
            last = ProviderError(f"DataForSEO server error {resp.status_code}",
                                 code="PROVIDER_UPSTREAM", retryable=True)
            time.sleep(2 ** attempt * 5)
            continue
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"DataForSEO bad JSON: {exc}") from exc
        task = (data.get("tasks") or [{}])[0]
        code = task.get("status_code")
        msg = task.get("status_message", "")
        if code == 20000:
            return task
        if code in (40100, 40101, 40102, 40103):
            raise ProviderAuthError(f"DataForSEO auth failed: {msg}")
        if code in (40200, 40201, 40202, 40203, 40204):
            raise ProviderQuotaError(f"DataForSEO billing/quota: {msg}")
        if code and 40000 <= code < 41000:
            raise ProviderError(f"DataForSEO rejected request: {msg} ({code})")
        last = ProviderError(f"DataForSEO error: {msg} ({code})", retryable=True)
        time.sleep(2 ** attempt * 5)
    raise last or ProviderError("DataForSEO request failed")


def _domain_of(url: str) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or "").lower()


def normalize_serp_items(items: list[dict]) -> tuple[list[SerpResultItem], list[dict]]:
    """Pure: vendor items → (ranked results, SERP features)."""
    results: list[SerpResultItem] = []
    features: list[dict] = []
    for it in items or []:
        itype = (it.get("type") or "").lower()
        if itype in ORGANIC_TYPES or itype in PAID_TYPES:
            results.append(SerpResultItem(
                position=int(it.get("rank_absolute") or it.get("rank_group") or 0),
                domain=_domain_of(it.get("url") or ""),
                url=it.get("url") or "",
                title=it.get("title"),
                snippet=it.get("description"),
                result_type="paid" if itype in PAID_TYPES else "organic",
            ))
        elif itype in FEATURE_TYPES:
            features.append({
                "feature_type": itype,
                "position": it.get("rank_absolute") or it.get("rank_group"),
                "data": {k: v for k, v in it.get("items", [{}])[0].items()
                         if k in ("title", "url", "domain", "description")}
                if isinstance(it.get("items"), list) and it.get("items") else {},
            })
    results.sort(key=lambda r: r.position)
    # re-number organic positions 1..N for stable storage
    n = 0
    for r in results:
        if r.result_type == "organic":
            n += 1
            r.position = n
    return results, features


def normalize_kw_item(item: dict, provider: str = "dataforseo") -> KeywordMetrics:
    monthly = item.get("monthly_searches") or []
    trend = [m.get("search_volume") for m in monthly[-12:] if isinstance(m, dict)]
    comp_index = item.get("competition_index")
    competition = (comp_index / 100.0) if isinstance(comp_index, (int, float)) else None
    return KeywordMetrics(
        keyword=item.get("keyword") or "",
        search_volume=item.get("search_volume"),
        cpc=item.get("cpc"),
        competition=competition,
        trend=trend or None,
        provider=provider,
    )


class DataForSEOSERP:
    """SERPProvider over DataForSEO Google Organic Live Advanced."""

    name = "dataforseo"

    def __init__(self, login: str, password: str):
        self.login = login
        self.password = password

    def search(self, keyword: str, *, country: str, language: str,
               device: str, location: str | None = None,
               location_code: int | None = None, depth: int = 20) -> SerpResponse:
        task = _post("/v3/serp/google/organic/live/advanced", [{
            "keyword": keyword,
            "location_code": location_code_for(country, location_code),
            "language_code": (language or "en").lower(),
            "device": DEVICE_MAP.get((device or "DESKTOP").upper(), "desktop"),
            "depth": max(10, min(int(depth or 20), 100)),
        }], self.login, self.password)
        result = (task.get("result") or [{}])[0]
        results, features = normalize_serp_items(result.get("items") or [])
        return SerpResponse(results=results, features=features,
                            provider_search_id=str(result.get("id") or ""),
                            raw={"se_check": result.get("se_check"),
                                 "check_url": result.get("check_url")})


class DataForSEOKeywords:
    """KeywordProvider over DataForSEO Google Ads live endpoints."""

    name = "dataforseo"

    def __init__(self, login: str, password: str):
        self.login = login
        self.password = password

    def _base(self, country: str, language: str) -> dict:
        return {"location_code": location_code_for(country),
                "language_code": (language or "en").lower()}

    def metrics(self, keywords: list[str], *, country: str,
                language: str) -> list[KeywordMetrics]:
        out: list[KeywordMetrics] = []
        for i in range(0, len(keywords), 200):
            chunk = keywords[i:i + 200]
            task = _post("/v3/keywords_data/google_ads/search_volume/live",
                         [{**self._base(country, language), "keywords": chunk}],
                         self.login, self.password)
            for item in task.get("result") or []:
                out.append(normalize_kw_item(item))
        return out

    def suggestions(self, seed: str, *, country: str, language: str,
                    limit: int = 100) -> list[KeywordMetrics]:
        task = _post("/v3/keywords_data/google_ads/keywords_for_keywords/live",
                     [{**self._base(country, language), "keywords": [seed],
                       "include_seed_keyword": True}],
                     self.login, self.password)
        out = [normalize_kw_item(item) for item in (task.get("result") or [])
               if item.get("keyword")]
        return out[:max(1, min(int(limit or 100), 1000))]
