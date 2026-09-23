"""SERP orchestration: persistent cache → provider → normalized storage.

Cache key covers keyword/country/language/device/location/engine/provider.
Freshness TTL avoids repeat billing for the same query (spec §24).
Every provider call is metered via ProviderUsage.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.providers import accounts as provider_accounts
from app.providers.base import ProviderError
from app.providers.dataforseo import DataForSEOSERP

SERP_CACHE_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(UTC)


def cache_key(*, keyword: str, engine: str, country: str, language: str,
              device: str, location: str | None, provider: str,
              project_id: uuid.UUID | None) -> str:
    raw = "|".join([(keyword or "").strip().lower(), engine.lower(),
                    country.upper(), language.lower(), device.upper(),
                    (location or "").strip().lower(), provider.lower(),
                    str(project_id or "global")])
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_provider(org_id: uuid.UUID, db: Session, provider: str):
    creds = provider_accounts.get_credentials(db, org_id, provider)
    if provider == "dataforseo":
        return DataForSEOSERP(creds["login"], creds["password"])
    raise ProviderError(f"no SERP implementation for provider {provider!r}")


def default_serp_provider(db: Session, org_id: uuid.UUID) -> str:
    """Org's configured SERP-capable provider. Raises KeyError if none."""
    from app.providers.registry import PROVIDERS
    rows = db.query(seo.ProviderAccount).filter_by(organization_id=org_id).all()
    configured = {r.provider for r in rows if r.status in ("CONFIGURED", "ACTIVE")}
    for name, meta in PROVIDERS.items():
        if "serp" in meta.get("kind", []) and name in configured:
            return name
    raise KeyError("no SERP provider configured")


def search_serp(db: Session, *, organization_id: uuid.UUID,
                project_id: uuid.UUID | None, keyword: str, engine: str = "google",
                country: str = "US", language: str = "en", device: str = "DESKTOP",
                location: str | None = None, location_code: int | None = None,
                depth: int = 20, provider: str | None = None,
                force_refresh: bool = False) -> tuple[seo.SerpSearch, bool]:
    """Returns (SerpSearch row, from_cache). Raises KeyError/ProviderError."""
    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("keyword is required")
    provider = provider or default_serp_provider(db, organization_id)
    key = cache_key(keyword=keyword, engine=engine, country=country,
                    language=language, device=device, location=location,
                    provider=provider, project_id=project_id)
    if not force_refresh:
        cached = db.query(seo.SerpSearch).filter_by(cache_key=key).first()
        if cached and cached.searched_at:
            age = utcnow() - cached.searched_at.replace(tzinfo=UTC) \
                if cached.searched_at.tzinfo is None else utcnow() - cached.searched_at
            if age <= timedelta(days=SERP_CACHE_DAYS):
                return cached, True

    impl = _get_provider(organization_id, db, provider)
    try:
        resp = impl.search(keyword, country=country, language=language,
                           device=device, location=location,
                           location_code=location_code, depth=depth)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"SERP provider failed: {exc}") from exc

    now = utcnow()
    row = db.query(seo.SerpSearch).filter_by(cache_key=key).first()
    if row is None:
        row = seo.SerpSearch(
            organization_id=organization_id, project_id=project_id, keyword=keyword,
            engine=engine, country=country.upper(), language=language.lower(),
            device=device.upper(), location=location, cache_key=key,
            status="COMPLETED", provider=provider, searched_at=now)
        db.add(row)
        db.flush()
    else:
        # Refresh in place: same cache identity, new provider snapshot.
        # Old results/features are replaced (rank history lives on
        # RankObservation rows, which reference tracked keywords, not this).
        db.query(seo.SerpResult).filter_by(serp_search_id=row.id).delete()
        db.query(seo.SerpFeature).filter_by(serp_search_id=row.id).delete()
        row.keyword = keyword
        row.engine = engine
        row.country = country.upper()
        row.language = language.lower()
        row.device = device.upper()
        row.location = location
    row.status = "COMPLETED"
    row.provider = provider
    row.provider_search_id = resp.provider_search_id
    row.searched_at = now
    row.raw_response = resp.raw
    db.flush()
    for item in resp.results:
        db.add(seo.SerpResult(
            serp_search_id=row.id, position=item.position, domain=item.domain,
            url=item.url[:2000], title=(item.title or "")[:1000],
            snippet=item.snippet, result_type=item.result_type,
            feature_type=item.feature_type))
    for feat in resp.features:
        db.add(seo.SerpFeature(serp_search_id=row.id,
                               feature_type=feat.get("feature_type", "unknown"),
                               position=feat.get("position"), data=feat.get("data")))
    provider_accounts.record_usage(db, organization_id, provider, "serp", "search",
                                   units=max(1, depth // 10))
    db.commit()
    db.refresh(row)
    return row, False


def find_rank(results: list[seo.SerpResult], domain: str) -> tuple[int | None, str | None]:
    """Best organic rank + URL for a domain in a stored result set."""
    def fold(d: str) -> str:
        d = (d or "").lower()
        return d.removeprefix("www.")

    target = fold(domain)
    for r in results:
        if r.result_type != "organic":
            continue
        d = fold(r.domain)
        if d == target or d.endswith("." + target) or target.endswith("." + d):
            return r.position, r.url
    return None, None
