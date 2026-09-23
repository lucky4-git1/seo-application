"""Reports: create jobs, list, download generated files."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.reports import FORMATS, REPORT_TYPES
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["reports"])


class ReportIn(BaseModel):
    type: str = Field(pattern="^(SEO_OVERVIEW|AUDIT|KEYWORDS|RANKINGS|COMPETITORS)$")
    format: str = Field(default="CSV", pattern="^(CSV|PDF)$")


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.post("/organizations/{org_id}/projects/{project_id}/reports",
             status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def create_report(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: ReportIn,
                  user: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    if body.type not in REPORT_TYPES or body.format not in FORMATS:
        raise HTTPException(status_code=400, detail="invalid report type/format")
    rep = seo.Report(organization_id=org_id, project_id=project.id,
                     type=body.type, status="PENDING",
                     params={"format": body.format}, created_by=user.id)
    db.add(rep)
    db.flush()
    exp = seo.ReportExport(report_id=rep.id, format=body.format, status="PENDING",
                           expires_at=_utcnow() + timedelta(days=7))
    db.add(exp)
    db.flush()
    job = jobstore.create_job(db, organization_id=org_id, project_id=project.id,
                              job_type="GENERATE_REPORT",
                              payload={"report_id": str(rep.id),
                                       "export_id": str(exp.id)})
    db.commit()
    celery.send_task("seo.generate_report", args=[str(job.id)],
                     kwargs={"report_id": str(rep.id), "export_id": str(exp.id)})
    return {"report": {"id": str(rep.id), "type": rep.type, "status": rep.status},
            "export": {"id": str(exp.id), "format": exp.format, "status": exp.status},
            "job": {"id": str(job.id), "status": job.status}}


@router.get("/organizations/{org_id}/projects/{project_id}/reports")
def list_reports(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = (db.query(seo.Report).filter_by(project_id=project.id)
         .order_by(seo.Report.created_at.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for r in rows:
        exps = db.query(seo.ReportExport).filter_by(report_id=r.id).all()
        items.append({
            "id": str(r.id), "type": r.type, "status": r.status,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "exports": [{"id": str(e.id), "format": e.format, "status": e.status,
                         "expires_at": e.expires_at.isoformat() if e.expires_at else None}
                        for e in exps]})
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/reports/exports/{export_id}/download")
def download_export(org_id: uuid.UUID, project_id: uuid.UUID, export_id: uuid.UUID,
                    user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    exp = db.get(seo.ReportExport, export_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="Export not found")
    rep = db.get(seo.Report, exp.report_id)
    if rep is None or rep.project_id != project.id:
        raise HTTPException(status_code=404, detail="Export not found")
    if exp.status != "READY" or not exp.file_path or not os.path.exists(exp.file_path):
        raise HTTPException(status_code=409, detail="Export not ready yet")
    if exp.expires_at and exp.expires_at.replace(tzinfo=UTC) < _utcnow():
        raise HTTPException(status_code=410, detail="Export expired")
    media = "text/csv" if exp.format == "CSV" else "application/pdf"
    return FileResponse(exp.file_path, media_type=media,
                        filename=f"report-{rep.type.lower()}.{exp.format.lower()}")
