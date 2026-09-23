"""Site audit endpoints — enqueue crawls, read runs, issues, instances.

Heavy work runs in Celery (see app/tasks.py); these routes only create rows,
enqueue, and read. Every route is tenant-scoped: the project must belong to
the organization and the caller must be a member.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.audit.rules import BUCKET_WEIGHTS, CATEGORY_TO_BUCKET, score_bucket
from app.database import get_db
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["audits"])


class AuditStart(BaseModel):
    max_pages: int = Field(default=200, ge=1, le=500)


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _run_out(run: seo.CrawlRun) -> dict:
    return {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "pages_discovered": run.pages_discovered,
        "pages_crawled": run.pages_crawled,
        "issues_found": run.issues_found,
        "health_score": run.health_score,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _issue_counts(db: Session, run_id: uuid.UUID) -> dict:
    rows = db.query(seo.AuditIssue.severity, seo.AuditIssue.category,
                    seo.AuditIssue.affected_count).filter_by(crawl_run_id=run_id).all()
    by_sev = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "NOTICE": 0}
    per_bucket: dict[str, list[dict]] = {b: [] for b in BUCKET_WEIGHTS}
    pages = db.query(seo.CrawlRun.pages_crawled).filter_by(id=run_id).scalar() or 0
    for sev, cat, affected in rows:
        by_sev[sev] = by_sev.get(sev, 0) + 1
        per_bucket[CATEGORY_TO_BUCKET.get(cat, "technical")].append(
            {"severity": sev, "affected_count": affected})
    buckets = {b: score_bucket(per_bucket[b], pages) for b in BUCKET_WEIGHTS}
    return {"by_severity": by_sev, "buckets": buckets, "rules_firing": sum(by_sev.values())}


@router.post("/organizations/{org_id}/projects/{project_id}/audits", status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def start_audit(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: AuditStart,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    from app import entitlements
    max_pages = entitlements.clamp_crawl_pages(db, org_id, body.max_pages)
    run = seo.CrawlRun(organization_id=org_id, project_id=project.id,
                       status="PENDING", config={"max_pages": max_pages})
    db.add(run)
    db.flush()
    job = jobstore.create_job(db, organization_id=org_id, project_id=project.id,
                              job_type="RUN_AUDIT",
                              payload={"run_id": str(run.id), "max_pages": max_pages})
    db.commit()
    # send by name so the API process never imports the worker-only
    # crawler/parser stack (bs4/lxml live in the worker image only).
    celery.send_task("seo.run_audit", args=[str(job.id), str(run.id), max_pages])
    out = _run_out(run)
    out["max_pages_applied"] = max_pages
    return {"run": out,
            "job": {"id": str(job.id), "status": job.status, "job_type": job.job_type}}


@router.get("/organizations/{org_id}/projects/{project_id}/audits")
def list_audits(org_id: uuid.UUID, project_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db),
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = (db.query(seo.CrawlRun).filter_by(project_id=project.id)
         .order_by(seo.CrawlRun.created_at.desc()))
    total = q.count()
    runs = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_run_out(r) for r in runs], "page": page,
            "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/audits/{run_id}")
def get_audit(org_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID,
              user: models.User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    run = db.get(seo.CrawlRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Audit not found")
    out = _run_out(run)
    out.update(_issue_counts(db, run.id))
    job = (db.query(models.Job).filter_by(project_id=project.id, job_type="RUN_AUDIT")
           .order_by(models.Job.created_at.desc()).first())
    out["job"] = ({"id": str(job.id), "status": job.status,
                   "progress": job.progress} if job else None)
    return out


@router.get("/organizations/{org_id}/projects/{project_id}/audits/{run_id}/issues")
def list_issues(org_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db),
                severity: str | None = Query(None),
                category: str | None = Query(None),
                search: str | None = Query(None),
                sort: str = Query("severity", pattern="^(severity|affected|recent)$"),
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    run = db.get(seo.CrawlRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Audit not found")
    q = (db.query(seo.AuditIssue, seo.AuditRule.code, seo.AuditRule.name)
         .join(seo.AuditRule, seo.AuditIssue.rule_id == seo.AuditRule.id)
         .filter(seo.AuditIssue.crawl_run_id == run.id))
    if severity:
        q = q.filter(seo.AuditIssue.severity == severity.upper())
    if category:
        q = q.filter(seo.AuditIssue.category == category)
    if search:
        like = f"%{search}%"
        q = q.filter((seo.AuditIssue.message.ilike(like))
                     | (seo.AuditRule.name.ilike(like))
                     | (seo.AuditRule.code.ilike(like)))
    sev_rank = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "NOTICE": 3}
    if sort == "affected":
        q = q.order_by(seo.AuditIssue.affected_count.desc())
    elif sort == "recent":
        q = q.order_by(seo.AuditIssue.last_seen.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [{
        "id": str(issue.id), "rule_code": code, "rule_name": name,
        "severity": issue.severity, "category": issue.category,
        "message": issue.message, "why_it_matters": issue.why_it_matters,
        "recommendation": issue.recommendation, "status": issue.status,
        "affected_count": issue.affected_count,
    } for issue, code, name in rows]
    if sort == "severity":
        items.sort(key=lambda i: (sev_rank.get(i["severity"], 9), -i["affected_count"]))
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/issues/{issue_id}/urls")
def issue_urls(org_id: uuid.UUID, project_id: uuid.UUID, issue_id: uuid.UUID,
               user: models.User = Depends(get_current_user),
               db: Session = Depends(get_db),
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    issue = db.get(seo.AuditIssue, issue_id)
    if issue is None or issue.project_id != project.id:
        raise HTTPException(status_code=404, detail="Issue not found")
    q = (db.query(seo.AuditIssueInstance)
         .filter_by(issue_id=issue.id).order_by(seo.AuditIssueInstance.url))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"url": r.url,
                       "detected_at": r.detected_at.isoformat()} for r in rows],
            "page": page, "page_size": page_size, "total": total,
            "affected_count": issue.affected_count}
