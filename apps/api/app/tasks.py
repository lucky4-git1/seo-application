"""Celery tasks — expensive work runs here, never inside HTTP requests.

Each task owns its DB session (created from the session factory so tests can
override the engine) and drives a Job row through PENDING → RUNNING →
COMPLETED | FAILED. Retries use exponential backoff for transient failures;
permanent failures (bad domain, blocked target) fail fast without retry.
"""
from __future__ import annotations

import uuid

from celery.exceptions import MaxRetriesExceededError

from app import jobs as jobstore
from app import models_seo as seo_models
from app.audit import engine as audit_engine
from app.celery_app import celery
from app.crawler import engine as crawl_engine
from app.database import get_session_factory
from app.models import Job
from app.providers.base import ProviderError

RETRYABLE_PREFIXES = ("network error", "body error", "timeout", "temporary")


def _is_retryable(message: str) -> bool:
    low = (message or "").lower()
    return any(p in low for p in RETRYABLE_PREFIXES)


@celery.task(name="seo.run_audit", bind=True, max_retries=3)
def run_audit_task(self, job_id: str, run_id: str, max_pages: int = 200) -> dict:
    """Crawl a project's domain, then evaluate audit rules. Returns summary."""
    Session = get_session_factory()
    db = Session()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        try:
            crawl_engine.run_crawl(db, uuid.UUID(run_id), max_pages=max_pages)
            summary = audit_engine.run_audit(db, uuid.UUID(run_id))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if _is_retryable(message):
                job.retry_count = (job.retry_count or 0) + 1
                db.commit()
                try:
                    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
                except MaxRetriesExceededError:
                    pass
            jobstore.mark_failed(db, job, message)
            return {"ok": False, "error": message}
        jobstore.mark_completed(db, job, summary)
        return {"ok": True, **summary}
    finally:
        db.close()


def _job_session(job_id: str):
    Session = get_session_factory()
    db = Session()
    job = db.get(Job, uuid.UUID(job_id))
    return db, job


@celery.task(name="seo.fetch_serp", bind=True, max_retries=3)
def fetch_serp_task(self, job_id: str, *, organization_id: str,
                    project_id: str | None, keyword: str, engine: str = "google",
                    country: str = "US", language: str = "en",
                    device: str = "DESKTOP", location: str | None = None,
                    depth: int = 20, force_refresh: bool = False) -> dict:
    """FETCH_SERP: cached-or-live SERP persisted to serp_* tables."""
    from fastapi import HTTPException

    import app.serp as serp_service
    from app import entitlements

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        try:
            entitlements.check_monthly(db, uuid.UUID(organization_id), "serp",
                                       "monthly_serp", "SERP request")
        except HTTPException as exc:
            jobstore.mark_failed(db, job, str(exc.detail))
            return {"ok": False, "error": str(exc.detail)}
        try:
            row, cached = serp_service.search_serp(
                db, organization_id=uuid.UUID(organization_id),
                project_id=uuid.UUID(project_id) if project_id else None,
                keyword=keyword, engine=engine, country=country,
                language=language, device=device, location=location,
                depth=depth, force_refresh=force_refresh)
        except (KeyError, ValueError) as exc:
            jobstore.mark_failed(db, job, str(exc))
            return {"ok": False, "error": str(exc)}
        except ProviderError as exc:
            if exc.retryable:
                job.retry_count = (job.retry_count or 0) + 1
                db.commit()
                try:
                    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
                except MaxRetriesExceededError:
                    pass
            jobstore.mark_failed(db, job, f"{exc.code}: {exc}")
            return {"ok": False, "error": str(exc)}
        summary = {"ok": True, "serp_search_id": str(row.id),
                   "from_cache": cached,
                   "results": len(row.results), "features": len(row.features)}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()


@celery.task(name="seo.fetch_keywords", bind=True, max_retries=3)
def fetch_keywords_task(self, job_id: str, *, organization_id: str,
                        project_id: str | None, seed: str, country: str = "US",
                        language: str = "en", limit: int = 100) -> dict:
    """FETCH_KEYWORDS: provider suggestions persisted + scored."""
    from fastapi import HTTPException

    from app import entitlements, keyword_service

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        try:
            entitlements.check_monthly(db, uuid.UUID(organization_id), "keywords",
                                       "monthly_keywords", "Keyword request")
        except HTTPException as exc:
            jobstore.mark_failed(db, job, str(exc.detail))
            return {"ok": False, "error": str(exc.detail)}
        try:
            views = keyword_service.research(
                db, organization_id=uuid.UUID(organization_id),
                project_id=uuid.UUID(project_id) if project_id else None,
                seed=seed, country=country, language=language, limit=limit)
        except (KeyError, ValueError) as exc:
            jobstore.mark_failed(db, job, str(exc))
            return {"ok": False, "error": str(exc)}
        except ProviderError as exc:
            if exc.retryable:
                job.retry_count = (job.retry_count or 0) + 1
                db.commit()
                try:
                    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
                except MaxRetriesExceededError:
                    pass
            jobstore.mark_failed(db, job, f"{exc.code}: {exc}")
            return {"ok": False, "error": str(exc)}
        summary = {"ok": True, "keywords": len(views)}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()


@celery.task(name="seo.track_rank", bind=True, max_retries=3)
def track_rank_task(self, job_id: str, *, tracked_keyword_id: str) -> dict:
    """TRACK_RANK: fresh SERP → rank observation for one tracked keyword."""
    from fastapi import HTTPException

    import app.serp as serp_service
    from app import entitlements
    from app.models import Project

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        t = db.get(seo_models.TrackedKeyword, uuid.UUID(tracked_keyword_id))
        if t is None or not t.is_active:
            jobstore.mark_failed(db, job, "tracked keyword missing or inactive")
            return {"ok": False, "error": "tracked keyword missing or inactive"}
        try:
            entitlements.check_monthly(db, t.organization_id, "serp",
                                       "monthly_serp", "SERP request")
        except HTTPException as exc:
            jobstore.mark_failed(db, job, str(exc.detail))
            return {"ok": False, "error": str(exc.detail)}
        project = db.get(Project, t.project_id)
        try:
            row, _cached = serp_service.search_serp(
                db, organization_id=t.organization_id, project_id=t.project_id,
                keyword=t.keyword, engine=t.engine, country=t.country,
                language=t.language, device=t.device, location=t.location,
                depth=20, force_refresh=True)
        except (KeyError, ValueError) as exc:
            jobstore.mark_failed(db, job, str(exc))
            return {"ok": False, "error": str(exc)}
        except ProviderError as exc:
            if exc.retryable:
                job.retry_count = (job.retry_count or 0) + 1
                db.commit()
                try:
                    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
                except MaxRetriesExceededError:
                    pass
            jobstore.mark_failed(db, job, f"{exc.code}: {exc}")
            return {"ok": False, "error": str(exc)}
        rank, url = serp_service.find_rank(row.results, project.domain)
        obs = seo_models.RankObservation(
            tracked_keyword_id=t.id, observed_at=jobstore.utcnow(),
            rank=rank, ranking_url=url,
            serp_features=[f.feature_type for f in row.features])
        db.add(obs)
        db.commit()
        summary = {"ok": True, "rank": rank, "url": url}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()


@celery.task(name="seo.track_scheduled_ranks")
def track_scheduled_ranks() -> dict:
    """Beat entry (daily): enqueue TRACK_RANK for every active tracked keyword
    whose project has a SERP provider configured. No provider → skipped."""
    import app.serp as serp_service

    Session = get_session_factory()
    db = Session()
    try:
        queued = skipped = 0
        for t in db.query(seo_models.TrackedKeyword).filter_by(is_active=True).all():
            try:
                serp_service.default_serp_provider(db, t.organization_id)
            except KeyError:
                skipped += 1
                continue
            job = jobstore.create_job(
                db, organization_id=t.organization_id, project_id=t.project_id,
                job_type="TRACK_RANK",
                payload={"tracked_keyword_id": str(t.id), "scheduled": True})
            db.commit()
            celery.send_task("seo.track_rank", args=[str(job.id)],
                             kwargs={"tracked_keyword_id": str(t.id)})
            queued += 1
        return {"queued": queued, "skipped_no_provider": skipped}
    finally:
        db.close()


@celery.task(name="seo.sync_gsc", bind=True, max_retries=3)
def sync_gsc_task(self, job_id: str, *, property_id: str, days: int = 90) -> dict:
    """SYNC_GSC: pull Search Analytics into gsc_* tables for one property."""
    import app.gsc as gsc_service

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        try:
            prop = db.get(seo_models.GscProperty, uuid.UUID(property_id))
            if prop is None:
                raise KeyError("GSC property not found")
            conn = db.get(seo_models.GscConnection, prop.connection_id)
            client = gsc_service.client_for(db, conn)
            stats = gsc_service.sync_property(db, prop, client, days=days)
        except (KeyError, ValueError) as exc:
            jobstore.mark_failed(db, job, str(exc))
            return {"ok": False, "error": str(exc)}
        except ProviderError as exc:
            if exc.retryable:
                job.retry_count = (job.retry_count or 0) + 1
                db.commit()
                try:
                    raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
                except MaxRetriesExceededError:
                    pass
            jobstore.mark_failed(db, job, f"{exc.code}: {exc}")
            return {"ok": False, "error": str(exc)}
        summary = {"ok": True, **stats}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()


@celery.task(name="seo.recalculate", bind=True, max_retries=2)
def recalculate_task(self, job_id: str, *, organization_id: str,
                     project_id: str) -> dict:
    """CALCULATE_RECOMMENDATIONS: regenerate OPEN recos for a project."""
    import app.recommendations as reco_engine

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        try:
            counts = reco_engine.recalculate(
                db, uuid.UUID(organization_id), uuid.UUID(project_id))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            jobstore.mark_failed(db, job, message)
            return {"ok": False, "error": message}
        summary = {"ok": True, **counts}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()


@celery.task(name="seo.generate_report", bind=True, max_retries=2)
def generate_report_task(self, job_id: str, *, report_id: str,
                         export_id: str) -> dict:
    """GENERATE_REPORT: build CSV/PDF bytes to the export dir."""
    from fastapi import HTTPException

    import app.reports as report_lib
    from app import entitlements
    from app.models import Project
    from app.providers import accounts as provider_accounts

    db, job = _job_session(job_id)
    try:
        if job is None:
            return {"ok": False, "error": "job not found"}
        jobstore.mark_running(db, job)
        rep = db.get(seo_models.Report, uuid.UUID(report_id))
        exp = db.get(seo_models.ReportExport, uuid.UUID(export_id))
        if rep is None or exp is None:
            jobstore.mark_failed(db, job, "report or export not found")
            return {"ok": False, "error": "report or export not found"}
        try:
            entitlements.check_monthly(db, rep.organization_id, "exports",
                                       "monthly_exports", "Report export")
        except HTTPException as exc:
            rep.status = "FAILED"
            rep.error = str(exc.detail)
            exp.status = "FAILED"
            exp.error = str(exc.detail)
            db.commit()
            jobstore.mark_failed(db, job, str(exc.detail))
            return {"ok": False, "error": str(exc.detail)}
        try:
            project = db.get(Project, rep.project_id)
            sections = report_lib.build_sections(db, project, rep.type)
            if exp.format == "PDF":
                payload = report_lib.build_pdf(
                    f"{rep.type} — {project.domain}", sections)
            else:
                payload = report_lib.build_csv(sections)
            path = report_lib.export_path(rep.id, exp.format)
            with open(path, "wb") as fh:
                fh.write(payload)
            exp.file_path = path
            exp.status = "READY"
            rep.status = "READY"
            provider_accounts.record_usage(db, rep.organization_id, "internal",
                                           "exports", "report", units=1)
            db.commit()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            rep.status = "FAILED"
            rep.error = message[:2000]
            exp.status = "FAILED"
            exp.error = message[:2000]
            db.commit()
            jobstore.mark_failed(db, job, message)
            return {"ok": False, "error": message}
        summary = {"ok": True, "format": exp.format, "bytes": len(payload)}
        jobstore.mark_completed(db, job, summary)
        return summary
    finally:
        db.close()
