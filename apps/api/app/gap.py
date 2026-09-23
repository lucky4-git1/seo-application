"""Keyword-gap computation shared by the API route and the recommendation
engine. Pure service: no auth, no HTTP — takes scoped rows, returns rows."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.keyword_service import scored_view
from app.keywords import normalize_keyword, opportunity_score
from app.serp import find_rank


def latest_serp_for(db: Session, project_id: uuid.UUID, keyword_norm: str,
                    country: str, device: str) -> seo.SerpSearch | None:
    best = None
    for s in db.query(seo.SerpSearch).filter_by(project_id=project_id).all():
        if normalize_keyword(s.keyword) != keyword_norm:
            continue
        if s.country != country or s.device != device:
            continue
        if best is None or (s.searched_at and best.searched_at and
                            s.searched_at > best.searched_at):
            best = s
    return best


def compute_gap(db: Session, project, comps: list[seo.Competitor], *,
                bucket: str | None = None, intent: str | None = None,
                min_volume: int | None = None,
                max_difficulty: float | None = None,
                page: int = 1, page_size: int = 50) -> dict:
    tracked = db.query(seo.TrackedKeyword).filter_by(project_id=project.id,
                                                     is_active=True).all()
    rows = []
    for t in tracked:
        obs = (db.query(seo.RankObservation)
               .filter_by(tracked_keyword_id=t.id)
               .order_by(seo.RankObservation.observed_at.desc()).first())
        your_rank = obs.rank if obs else None
        serp = latest_serp_for(db, project.id, t.normalized_keyword,
                               t.country, t.device)
        comp_ranks = {}
        for c in comps:
            r, _u = find_rank(serp.results, c.domain) if serp else (None, None)
            comp_ranks[str(c.id)] = r
        ranked_comps = [r for r in comp_ranks.values() if r is not None]
        if your_rank is None and ranked_comps:
            b = "missing"
        elif your_rank is not None and ranked_comps and your_rank > min(ranked_comps):
            b = "weak"
        elif your_rank is not None and (not ranked_comps or your_rank <= min(ranked_comps)):
            b = "strong"
        else:
            b = "shared"
        if bucket and b != bucket:
            continue
        kw = db.get(seo.Keyword, t.keyword_id) if t.keyword_id else None
        if kw is None:
            # tracked before any research ran: match stored keyword metrics
            kw = (db.query(seo.Keyword)
                  .filter_by(organization_id=project.organization_id,
                             normalized_keyword=t.normalized_keyword,
                             country=t.country, language=t.language).first())
        view = scored_view(db, kw, current_rank=your_rank) if kw else None
        if intent and (view or {}).get("intent") != intent.upper():
            continue
        if min_volume is not None and ((view or {}).get("search_volume") or 0) < min_volume:
            continue
        if max_difficulty is not None and ((view or {}).get("difficulty") or 101) > max_difficulty:
            continue
        opp = (view or {}).get("opportunity")
        if opp is None:
            opp = opportunity_score(search_volume=(view or {}).get("search_volume"),
                                    difficulty=(view or {}).get("difficulty"),
                                    intent=(view or {}).get("intent"),
                                    current_rank=your_rank)
        rows.append({
            "keyword": t.keyword, "your_rank": your_rank,
            "competitor_ranks": comp_ranks, "bucket": b,
            "search_volume": (view or {}).get("search_volume"),
            "difficulty": (view or {}).get("difficulty"),
            "intent": (view or {}).get("intent"),
            "opportunity": opp,
        })
    rows.sort(key=lambda r: (-(r["opportunity"] or 0), r["keyword"]))
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size], "page": page,
        "page_size": page_size, "total": total,
        "competitors": [{"id": str(c.id), "domain": c.domain} for c in comps],
    }
