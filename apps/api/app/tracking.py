"""Rank-tracking service: movement computation shared by API + engine."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import models_seo as seo


def movement(db: Session, t: seo.TrackedKeyword) -> dict:
    obs = (db.query(seo.RankObservation).filter_by(tracked_keyword_id=t.id)
           .order_by(seo.RankObservation.observed_at.desc()).limit(60).all())
    ranks = [o.rank for o in obs if o.rank is not None]
    current = obs[0].rank if obs else None
    current_url = obs[0].ranking_url if obs else None
    prev = next((o.rank for o in obs[1:] if o.rank is not None), None)
    change = (prev - current) if (current is not None and prev is not None) else None
    return {
        "id": str(t.id), "keyword": t.keyword, "country": t.country,
        "language": t.language, "device": t.device, "engine": t.engine,
        "location": t.location, "is_active": t.is_active,
        "current_rank": current, "current_url": current_url,
        "previous_rank": prev, "change": change,
        "best_rank": min(ranks) if ranks else None,
        "worst_rank": max(ranks) if ranks else None,
        "observations": len(obs),
        "last_checked_at": obs[0].observed_at.isoformat() if obs else None,
    }
