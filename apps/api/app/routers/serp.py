"""SERP analysis endpoints — live search via jobs, cached reads."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["serp"])


class SerpSearchIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=500)
    country: str = Field(default="US", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=10)
    device: str = Field(default="DESKTOP")
    location: str | None = Field(default=None, max_length=200)
    location_code: int | None = None
    depth: int = Field(default=20, ge=10, le=100)
    force_refresh: bool = False

    @classmethod
    def _check_device(cls, v: str) -> str:
        if v not in ("DESKTOP", "MOBILE"):
            raise ValueError("device must be DESKTOP|MOBILE")
        return v


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _search_out(row: seo.SerpSearch, n_results: int = 0, n_features: int = 0) -> dict:
    return {
        "id": str(row.id), "keyword": row.keyword, "engine": row.engine,
        "country": row.country, "language": row.language, "device": row.device,
        "location": row.location, "status": row.status, "provider": row.provider,
        "searched_at": row.searched_at.isoformat() if row.searched_at else None,
        "results": n_results, "features": n_features,
    }


@router.post("/organizations/{org_id}/projects/{project_id}/serp/search",
             status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def serp_search(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: SerpSearchIn,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    device = SerpSearchIn._check_device(body.device)
    job = jobstore.create_job(
        db, organization_id=org_id, project_id=project.id, job_type="FETCH_SERP",
        payload={"keyword": body.keyword, "country": body.country,
                 "language": body.language, "device": device,
                 "location": body.location, "depth": body.depth,
                 "force_refresh": body.force_refresh})
    db.commit()
    celery.send_task("seo.fetch_serp", args=[str(job.id)], kwargs={
        "organization_id": str(org_id), "project_id": str(project.id),
        "keyword": body.keyword, "country": body.country.upper(),
        "language": body.language.lower(), "device": device,
        "location": body.location, "depth": body.depth,
        "force_refresh": body.force_refresh})
    return {"job": {"id": str(job.id), "status": job.status, "job_type": job.job_type}}


@router.get("/organizations/{org_id}/projects/{project_id}/serp")
def serp_history(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = (db.query(seo.SerpSearch).filter_by(project_id=project.id)
         .order_by(seo.SerpSearch.searched_at.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for r in rows:
        n = db.query(seo.SerpResult).filter_by(serp_search_id=r.id).count()
        f = db.query(seo.SerpFeature).filter_by(serp_search_id=r.id).count()
        items.append(_search_out(r, n, f))
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/serp/{search_id}")
def serp_detail(org_id: uuid.UUID, project_id: uuid.UUID, search_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    row = db.get(seo.SerpSearch, search_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="SERP search not found")
    results = (db.query(seo.SerpResult).filter_by(serp_search_id=row.id)
               .order_by(seo.SerpResult.position).all())
    features = db.query(seo.SerpFeature).filter_by(serp_search_id=row.id).all()
    out = _search_out(row, len(results), len(features))
    out["result_items"] = [{
        "position": r.position, "domain": r.domain, "url": r.url,
        "title": r.title, "snippet": r.snippet, "result_type": r.result_type,
        "feature_type": r.feature_type} for r in results]
    out["feature_items"] = [{
        "feature_type": f.feature_type, "position": f.position,
        "data": f.data} for f in features]
    return out
