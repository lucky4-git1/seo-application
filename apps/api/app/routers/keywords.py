"""Keyword research endpoints — provider research via jobs, stored reads."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.keyword_service import scored_view
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["keywords"])


class ResearchIn(BaseModel):
    seed: str = Field(min_length=1, max_length=500)
    country: str = Field(default="US", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=10)
    limit: int = Field(default=100, ge=1, le=1000)


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


@router.post("/organizations/{org_id}/projects/{project_id}/keywords/research",
             status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def keyword_research(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: ResearchIn,
                     user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    job = jobstore.create_job(
        db, organization_id=org_id, project_id=project.id, job_type="FETCH_KEYWORDS",
        payload={"seed": body.seed, "country": body.country,
                 "language": body.language, "limit": body.limit})
    db.commit()
    celery.send_task("seo.fetch_keywords", args=[str(job.id)], kwargs={
        "organization_id": str(org_id), "project_id": str(project.id),
        "seed": body.seed, "country": body.country.upper(),
        "language": body.language.lower(), "limit": body.limit})
    return {"job": {"id": str(job.id), "status": job.status, "job_type": job.job_type}}


@router.get("/organizations/{org_id}/projects/{project_id}/keywords")
def keyword_list(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 search: str | None = Query(None),
                 intent: str | None = Query(None),
                 min_volume: int | None = Query(None, ge=0),
                 max_difficulty: float | None = Query(None, ge=0, le=100),
                 sort: str = Query("opportunity",
                                   pattern="^(opportunity|volume|difficulty|keyword|updated)$"),
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = db.query(seo.Keyword).filter(
        seo.Keyword.organization_id == org_id,
        ((seo.Keyword.project_id == project.id) | (seo.Keyword.project_id.is_(None))))
    if search:
        q = q.filter(seo.Keyword.normalized_keyword.ilike(f"%{search.strip().lower()}%"))
    rows = q.order_by(seo.Keyword.created_at.desc()).limit(2000).all()

    views = []
    for kw in rows:
        v = scored_view(db, kw)
        if intent and (v["intent"] or "") != intent.upper():
            continue
        if min_volume is not None and (v["search_volume"] or 0) < min_volume:
            continue
        if max_difficulty is not None and (v["difficulty"] or 0) > max_difficulty:
            continue
        views.append(v)
    sorters = {
        "opportunity": lambda v: -(v["opportunity"] or 0),
        "volume": lambda v: -(v["search_volume"] or 0),
        "difficulty": lambda v: (v["difficulty"] if v["difficulty"] is not None else 101),
        "keyword": lambda v: v["keyword"],
        "updated": lambda v: v["updated_at"] or "",
    }
    views.sort(key=sorters[sort])
    total = len(views)
    start = (page - 1) * page_size
    return {"items": views[start:start + page_size], "page": page,
            "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/keywords/{keyword_id}")
def keyword_detail(org_id: uuid.UUID, project_id: uuid.UUID, keyword_id: uuid.UUID,
                   user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    kw = db.get(seo.Keyword, keyword_id)
    if kw is None or kw.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Keyword not found")
    _ = project
    history = (db.query(seo.KeywordMetric).filter_by(keyword_id=kw.id)
               .order_by(seo.KeywordMetric.created_at.desc()).limit(30).all())
    out = scored_view(db, kw)
    out["history"] = [{
        "search_volume": m.search_volume, "cpc": m.cpc,
        "competition": m.competition, "difficulty": m.difficulty,
        "opportunity": m.opportunity, "provider": m.provider,
        "observed_at": m.created_at.isoformat()} for m in history]
    return out
