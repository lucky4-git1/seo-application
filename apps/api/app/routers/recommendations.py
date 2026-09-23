"""Recommendations (Action Center): list, status transitions, recalculate."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["recommendations"])

STATUSES = ("OPEN", "IN_PROGRESS", "DISMISSED", "COMPLETED")


class StatusIn(BaseModel):
    status: str = Field(pattern="^(OPEN|IN_PROGRESS|DISMISSED|COMPLETED)$")


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _out(r: seo.Recommendation) -> dict:
    return {
        "id": str(r.id), "type": r.type, "source": r.source,
        "severity": r.severity, "impact": r.impact, "effort": r.effort,
        "confidence": r.confidence, "score": r.score, "title": r.title,
        "description": r.description, "why": r.why,
        "recommended_action": r.recommended_action,
        "related_url": r.related_url, "related_keyword": r.related_keyword,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/organizations/{org_id}/projects/{project_id}/recommendations")
def list_recommendations(
        org_id: uuid.UUID, project_id: uuid.UUID,
        user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
        type: str | None = Query(None),
        source: str | None = Query(None),
        severity: str | None = Query(None),
        status: str | None = Query(None),
        min_score: float | None = Query(None, ge=0, le=100),
        sort: str = Query("score", pattern="^(score|severity|recent)$"),
        page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = db.query(seo.Recommendation).filter_by(project_id=project.id)
    if type:
        q = q.filter(seo.Recommendation.type == type.upper())
    if source:
        q = q.filter(seo.Recommendation.source == source.upper())
    if severity:
        q = q.filter(seo.Recommendation.severity == severity.upper())
    if status:
        q = q.filter(seo.Recommendation.status == status.upper())
    if min_score is not None:
        q = q.filter(seo.Recommendation.score >= min_score)
    total = q.count()
    if sort == "score":
        q = q.order_by(seo.Recommendation.score.desc())
    elif sort == "recent":
        q = q.order_by(seo.Recommendation.created_at.desc())
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    if sort == "severity":
        order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "NOTICE": 3}
        rows = sorted(rows, key=lambda r: (order.get(r.severity, 9), -r.score))
    by_status = dict(
        db.query(seo.Recommendation.status, func.count())
        .filter_by(project_id=project.id)
        .group_by(seo.Recommendation.status).all())
    return {"items": [_out(r) for r in rows], "page": page,
            "page_size": page_size, "total": total, "by_status": by_status}


@router.patch("/recommendations/{reco_id}")
def update_recommendation(reco_id: uuid.UUID, body: StatusIn,
                          user: models.User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    row = db.get(seo.Recommendation, reco_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    require_org_role(db, user.id, row.organization_id, {"OWNER", "ADMIN", "MEMBER"})
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    row.status = body.status
    db.commit()
    return _out(row)


@router.post("/organizations/{org_id}/projects/{project_id}/recommendations/recalculate",
             status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def recalculate(request: Request, org_id: uuid.UUID, project_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    job = jobstore.create_job(db, organization_id=org_id, project_id=project.id,
                              job_type="CALCULATE_RECOMMENDATIONS", payload={})
    db.commit()
    celery.send_task("seo.recalculate", args=[str(job.id)],
                     kwargs={"organization_id": str(org_id),
                             "project_id": str(project.id)})
    return {"job": {"id": str(job.id), "status": job.status, "job_type": job.job_type}}
