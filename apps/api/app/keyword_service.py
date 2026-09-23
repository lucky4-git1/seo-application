"""Keyword research orchestration: provider → dedup → metrics → scoring.

Writes Keyword + KeywordMetric + KeywordIntent rows (Step 2 schema) and
returns view-ready dicts. Metered via ProviderUsage.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.keywords import (
    classify_intent,
    keyword_difficulty,
    normalize_keyword,
    opportunity_score,
)
from app.providers import accounts as provider_accounts
from app.providers.base import KeywordMetrics, ProviderError
from app.providers.dataforseo import DataForSEOKeywords


def utcnow() -> datetime:
    return datetime.now(UTC)


def _get_provider(org_id: uuid.UUID, db: Session, provider: str):
    creds = provider_accounts.get_credentials(db, org_id, provider)
    if provider == "dataforseo":
        return DataForSEOKeywords(creds["login"], creds["password"])
    raise ProviderError(f"no keyword implementation for provider {provider!r}")


def default_keyword_provider(db: Session, org_id: uuid.UUID) -> str:
    from app.providers.registry import PROVIDERS
    rows = db.query(seo.ProviderAccount).filter_by(organization_id=org_id).all()
    configured = {r.provider for r in rows if r.status in ("CONFIGURED", "ACTIVE")}
    for name, meta in PROVIDERS.items():
        if "keyword" in meta.get("kind", []) and name in configured:
            return name
    raise KeyError("no keyword provider configured")


def store_metrics(db: Session, *, organization_id: uuid.UUID,
                  project_id: uuid.UUID | None, country: str, language: str,
                  source: str, items: list[KeywordMetrics]) -> list[seo.Keyword]:
    """Upsert keywords + append metric/intent rows. Returns Keyword rows."""
    out: list[seo.Keyword] = []
    for item in items:
        norm = normalize_keyword(item.keyword)
        if not norm:
            continue
        kw = (db.query(seo.Keyword)
              .filter_by(organization_id=organization_id, normalized_keyword=norm,
                         country=country.upper(), language=language.lower()).first())
        if kw is None:
            kw = seo.Keyword(organization_id=organization_id, project_id=project_id,
                             keyword=item.keyword.strip(), normalized_keyword=norm,
                             country=country.upper(), language=language.lower(),
                             source=source)
            db.add(kw)
            db.flush()
        intent, conf = classify_intent(item.keyword)
        db.add(seo.KeywordMetric(
            keyword_id=kw.id, search_volume=item.search_volume, cpc=item.cpc,
            competition=item.competition, trend=item.trend, intent=intent,
            difficulty=None, opportunity=None, provider=item.provider))
        existing = (db.query(seo.KeywordIntent)
                    .filter_by(keyword_id=kw.id, method="heuristic").first())
        if existing is None:
            db.add(seo.KeywordIntent(keyword_id=kw.id, intent=intent,
                                     confidence=conf, method="heuristic"))
        out.append(kw)
    db.commit()
    return out


def scored_view(db: Session, kw: seo.Keyword,
                serp_top10: list[dict] | None = None,
                current_rank: int | None = None) -> dict:
    """Latest metric + computed difficulty/opportunity for one keyword."""
    metric = (db.query(seo.KeywordMetric).filter_by(keyword_id=kw.id)
              .order_by(seo.KeywordMetric.created_at.desc()).first())
    intent_row = (db.query(seo.KeywordIntent).filter_by(keyword_id=kw.id)
                  .order_by(seo.KeywordIntent.confidence.desc()).first())
    vol = metric.search_volume if metric else None
    comp = metric.competition if metric else None
    intent = intent_row.intent if intent_row else (metric.intent if metric else None)
    difficulty, diff_note = keyword_difficulty(serp_results=serp_top10,
                                               competition=comp, search_volume=vol)
    opportunity = opportunity_score(search_volume=vol, difficulty=difficulty,
                                    intent=intent, current_rank=current_rank)
    return {
        "id": str(kw.id), "keyword": kw.keyword, "country": kw.country,
        "language": kw.language, "intent": intent,
        "intent_confidence": intent_row.confidence if intent_row else None,
        "search_volume": vol, "cpc": metric.cpc if metric else None,
        "competition": comp,
        "trend": metric.trend if metric else None,
        "difficulty": difficulty, "difficulty_note": diff_note,
        "opportunity": opportunity,
        "serp_features": metric.serp_features if metric else None,
        "provider": metric.provider if metric else None,
        "updated_at": metric.created_at.isoformat() if metric else None,
    }


def research(db: Session, *, organization_id: uuid.UUID,
             project_id: uuid.UUID | None, seed: str, country: str = "US",
             language: str = "en", limit: int = 100,
             provider: str | None = None) -> list[dict]:
    """Seed → provider suggestions → stored rows → scored views."""
    seed = (seed or "").strip()
    if not seed:
        raise ValueError("seed keyword is required")
    provider = provider or default_keyword_provider(db, organization_id)
    impl = _get_provider(organization_id, db, provider)
    try:
        items = impl.suggestions(seed, country=country, language=language, limit=limit)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"keyword provider failed: {exc}") from exc
    rows = store_metrics(db, organization_id=organization_id, project_id=project_id,
                         country=country, language=language,
                         source=f"{provider}:suggestions", items=items)
    provider_accounts.record_usage(db, organization_id, provider, "keywords",
                                   "suggestions", units=max(1, len(rows) // 10))
    return [scored_view(db, kw) for kw in rows]
