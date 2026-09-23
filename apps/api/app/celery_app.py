"""Celery app + job-type registry. Expensive work must go through here, never inline in requests."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

JOB_TYPES = (
    "CRAWL_SITE",
    "RUN_AUDIT",
    "FETCH_SERP",
    "FETCH_KEYWORDS",
    "TRACK_RANK",
    "SYNC_GSC",
    "GENERATE_REPORT",
    "CALCULATE_RECOMMENDATIONS",
    "AI_ANALYSIS",
)

JOB_STATUSES = ("PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")


def make_celery() -> Celery:
    s = get_settings()
    app = Celery("seo", broker=s.celery_broker_url, backend=s.celery_result_backend)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        beat_schedule={
            # Daily rank refresh. Skips projects without a SERP provider.
            "track-scheduled-ranks-daily": {
                "task": "seo.track_scheduled_ranks",
                "schedule": crontab(hour=3, minute=0),
            },
        },
    )
    return app


celery = make_celery()

# Lazy task discovery: the worker imports app.tasks at startup, while the
# API process (which also imports this module to enqueue via send_task)
# never pays for the worker-only crawler/parser stack (bs4/lxml).
celery.autodiscover_tasks(["app"])
