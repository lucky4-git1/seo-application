"""Rank tracking: tracked keywords, observations, movements, history."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.keywords import normalize_keyword
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org
from app.tracking import movement

router = APIRouter(tags=["rankings"])


class TrackedIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=500)
    country: str = Field(default="US", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=10)
    device: str = Field(default="DESKTOP")
    engine: str = Field(default="google")
    location: str | None = Field(default=None, max_length=200)


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


@router.post("/organizations/{org_id}/projects/{project_id}/tracked-keywords",
             status_code=201)
@limiter.limit(EXPENSIVE_LIMIT)
def add_tracked(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: TrackedIn,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    from app import entitlements
    entitlements.check_tracked(db, project.id, org_id)
    if body.device not in ("DESKTOP", "MOBILE"):
        raise HTTPException(status_code=400, detail="device must be DESKTOP|MOBILE")
    norm = normalize_keyword(body.keyword)
    if not norm:
        raise HTTPException(status_code=400, detail="invalid keyword")
    existing = (db.query(seo.TrackedKeyword)
                .filter_by(project_id=project.id, normalized_keyword=norm,
                           country=body.country.upper(), device=body.device,
                           engine=body.engine).first())
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
        return movement(db, existing)
    kw = (db.query(seo.Keyword)
          .filter_by(organization_id=org_id, normalized_keyword=norm,
                     country=body.country.upper(),
                     language=body.language.lower()).first())
    t = seo.TrackedKeyword(
        organization_id=org_id, project_id=project.id,
        keyword_id=kw.id if kw else None, keyword=body.keyword.strip(),
        normalized_keyword=norm, country=body.country.upper(),
        language=body.language.lower(), device=body.device, engine=body.engine,
        location=body.location)
    db.add(t)
    db.flush()
    job = jobstore.create_job(db, organization_id=org_id, project_id=project.id,
                              job_type="TRACK_RANK",
                              payload={"tracked_keyword_id": str(t.id)})
    db.commit()
    celery.send_task("seo.track_rank", args=[str(job.id)],
                     kwargs={"tracked_keyword_id": str(t.id)})
    db.refresh(t)
    return movement(db, t)


@router.get("/organizations/{org_id}/projects/{project_id}/tracked-keywords")
def list_tracked(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 active_only: bool = Query(True),
                 page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = db.query(seo.TrackedKeyword).filter_by(project_id=project.id)
    if active_only:
        q = q.filter_by(is_active=True)
    total = q.count()
    rows = (q.order_by(seo.TrackedKeyword.keyword)
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [movement(db, t) for t in rows], "page": page,
            "page_size": page_size, "total": total}


@router.delete("/organizations/{org_id}/projects/{project_id}/tracked-keywords/{tk_id}",
               status_code=204)
def remove_tracked(org_id: uuid.UUID, project_id: uuid.UUID, tk_id: uuid.UUID,
                   user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    t = db.get(seo.TrackedKeyword, tk_id)
    if t is None or t.project_id != project.id:
        raise HTTPException(status_code=404, detail="Tracked keyword not found")
    t.is_active = False
    db.commit()


@router.get("/organizations/{org_id}/projects/{project_id}/tracked-keywords/{tk_id}/history")
def rank_history(org_id: uuid.UUID, project_id: uuid.UUID, tk_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 days: int = Query(90, ge=1, le=730)):
    from datetime import timedelta

    from app.audit.engine import utcnow
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    t = db.get(seo.TrackedKeyword, tk_id)
    if t is None or t.project_id != project.id:
        raise HTTPException(status_code=404, detail="Tracked keyword not found")
    since = utcnow() - timedelta(days=days)
    obs = (db.query(seo.RankObservation)
           .filter(seo.RankObservation.tracked_keyword_id == t.id,
                   seo.RankObservation.observed_at >= since)
           .order_by(seo.RankObservation.observed_at).all())
    return {"items": [{
        "observed_at": o.observed_at.isoformat(), "rank": o.rank,
        "ranking_url": o.ranking_url,
        "serp_features": o.serp_features} for o in obs]}
