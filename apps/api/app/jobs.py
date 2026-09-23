"""Job row lifecycle helper — the single place that mutates jobs.* rows.

States: PENDING → RUNNING → COMPLETED | FAILED (CANCELLED set by callers).
Progress is a 0–100 int written by long tasks (crawl writes its own counters;
job progress mirrors them where cheap).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_job(db: Session, *, organization_id, project_id, job_type: str,
               payload: dict | None = None) -> models.Job:
    job = models.Job(organization_id=organization_id, project_id=project_id,
                     job_type=job_type, status="PENDING", progress=0,
                     payload=payload or {})
    # jobs table may predate payload/result columns on old DBs — set defensively
    db.add(job)
    db.flush()
    return job


def mark_running(db: Session, job: models.Job) -> None:
    job.status = "RUNNING"
    job.started_at = utcnow()
    db.commit()


def mark_progress(db: Session, job: models.Job, progress: int) -> None:
    job.progress = max(0, min(100, int(progress)))
    db.commit()


def mark_completed(db: Session, job: models.Job, result: dict | None = None) -> None:
    job.status = "COMPLETED"
    job.progress = 100
    job.finished_at = utcnow()
    job.result = result or {}
    db.commit()


def mark_failed(db: Session, job: models.Job, error: str) -> None:
    job.status = "FAILED"
    job.finished_at = utcnow()
    job.error = (error or "unknown error")[:2000]
    db.commit()
