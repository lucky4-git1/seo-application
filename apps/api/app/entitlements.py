"""Entitlements — plan limits enforced at creation points (Step 17).

Plans live on organizations.plan (FREE|PRO|BUSINESS). Enforcement raises
EntitlementError (mapped to HTTP 402 with an upgrade message); audits clamp
max_pages instead of rejecting. Stripe billing itself is a documented
future step (docs/billing.md) — limits are the foundation it will drive.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models_seo as seo

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "FREE": {
        "projects": 3,
        "tracked_per_project": 25,
        "crawl_pages": 200,
        "monthly_serp": 100,
        "monthly_keywords": 100,
        "monthly_exports": 10,
    },
    "PRO": {
        "projects": 25,
        "tracked_per_project": 500,
        "crawl_pages": 2000,
        "monthly_serp": 5000,
        "monthly_keywords": 5000,
        "monthly_exports": 500,
    },
    "BUSINESS": {
        "projects": 200,
        "tracked_per_project": 5000,
        "crawl_pages": 10000,
        "monthly_serp": 50000,
        "monthly_keywords": 50000,
        "monthly_exports": 5000,
    },
}


def plan_of(db: Session, org_id: uuid.UUID) -> str:
    from app import models
    org = db.get(models.Organization, org_id)
    plan = (org.plan if org else "FREE") or "FREE"
    return plan if plan in PLAN_LIMITS else "FREE"


def limits_for(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    return PLAN_LIMITS[plan_of(db, org_id)]


def _deny(what: str, limit: int, plan: str) -> HTTPException:
    return HTTPException(
        status_code=402,
        detail=f"{what} limit reached ({limit} on {plan} plan). Upgrade to raise it.")


def check_projects(db: Session, org_id: uuid.UUID) -> None:
    from app import models
    plan, limits = plan_of(db, org_id), limits_for(db, org_id)
    n = (db.query(func.count()).select_from(models.Project)
         .filter_by(organization_id=org_id, is_deleted=False).scalar() or 0)
    if n >= limits["projects"]:
        raise _deny("Project", limits["projects"], plan)


def check_tracked(db: Session, project_id: uuid.UUID, org_id: uuid.UUID) -> None:
    plan, limits = plan_of(db, org_id), limits_for(db, org_id)
    n = (db.query(func.count()).select_from(seo.TrackedKeyword)
         .filter_by(project_id=project_id, is_active=True).scalar() or 0)
    if n >= limits["tracked_per_project"]:
        raise _deny("Tracked keyword", limits["tracked_per_project"], plan)


def clamp_crawl_pages(db: Session, org_id: uuid.UUID, requested: int) -> int:
    return max(1, min(int(requested or 0), limits_for(db, org_id)["crawl_pages"]))


def month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_usage(db: Session, org_id: uuid.UUID, service: str) -> int:
    return int(db.query(func.coalesce(func.sum(seo.ProviderUsage.units), 0))
               .filter(seo.ProviderUsage.organization_id == org_id,
                       seo.ProviderUsage.service == service,
                       seo.ProviderUsage.created_at >= month_start()).scalar() or 0)


def check_monthly(db: Session, org_id: uuid.UUID, service: str,
                  limit_key: str, label: str) -> None:
    plan, limits = plan_of(db, org_id), limits_for(db, org_id)
    if monthly_usage(db, org_id, service) >= limits[limit_key]:
        raise _deny(label, limits[limit_key], plan)


def usage_snapshot(db: Session, org_id: uuid.UUID) -> dict:
    plan, limits = plan_of(db, org_id), limits_for(db, org_id)
    from app import models
    projects = (db.query(func.count()).select_from(models.Project)
                .filter_by(organization_id=org_id, is_deleted=False).scalar() or 0)
    return {
        "plan": plan,
        "limits": limits,
        "usage": {
            "projects": projects,
            "monthly_serp": monthly_usage(db, org_id, "serp"),
            "monthly_keywords": monthly_usage(db, org_id, "keywords"),
            "monthly_exports": monthly_usage(db, org_id, "exports"),
        },
    }
