"""Project overview — aggregates real per-module state for the SEO dashboard.

Every number comes from stored rows; anything without data returns null/[]
so the UI renders honest empty states. Never fabricate.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app import models_seo as seo
from app.database import get_db
from app.repositories import project_to_out
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["overview"])


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


@router.get("/organizations/{org_id}/projects/{project_id}/overview")
def project_overview(org_id: uuid.UUID, project_id: uuid.UUID,
                     user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)

    run = (db.query(seo.CrawlRun).filter_by(project_id=project.id)
           .order_by(seo.CrawlRun.created_at.desc()).first())
    audit = None
    if run is not None:
        sev_rows = (db.query(seo.AuditIssue.severity, func.count())
                    .filter_by(crawl_run_id=run.id).group_by(seo.AuditIssue.severity).all())
        audit = {
            "run_id": str(run.id),
            "status": run.status,
            "health_score": run.health_score,
            "pages_crawled": run.pages_crawled,
            "pages_discovered": run.pages_discovered,
            "issues_found": run.issues_found,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "by_severity": {sev: n for sev, n in sev_rows},
        }

    tracked_total = (db.query(func.count()).select_from(seo.TrackedKeyword)
                     .filter_by(project_id=project.id, is_active=True).scalar() or 0)
    competitor_total = (db.query(func.count()).select_from(seo.Competitor)
                        .filter_by(project_id=project.id, is_active=True).scalar() or 0)
    open_recos = (db.query(func.count()).select_from(seo.Recommendation)
                  .filter_by(project_id=project.id, status="OPEN").scalar() or 0)
    top_recos = (db.query(seo.Recommendation)
                 .filter_by(project_id=project.id, status="OPEN")
                 .order_by(seo.Recommendation.score.desc()).limit(3).all())
    gsc_connected = (db.query(seo.GscProperty).join(
        seo.GscConnection, seo.GscProperty.connection_id == seo.GscConnection.id)
        .filter(seo.GscConnection.organization_id == org_id,
                seo.GscProperty.project_id == project.id,
                seo.GscProperty.is_selected.is_(True)).count() > 0)
    job = (db.query(models.Job).filter_by(project_id=project.id)
           .order_by(models.Job.created_at.desc()).first())

    return {
        "project": project_to_out(project),
        "audit": audit,
        "tracked_keywords": tracked_total,
        "competitors": competitor_total,
        "open_recommendations": open_recos,
        "top_opportunities": [{
            "id": str(r.id), "title": r.title, "score": r.score,
            "severity": r.severity, "type": r.type,
        } for r in top_recos],
        "gsc_connected": gsc_connected,
        "latest_job": ({"id": str(job.id), "job_type": job.job_type,
                        "status": job.status, "progress": job.progress}
                       if job else None),
    }
