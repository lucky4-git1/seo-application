"""Repositories — only place that talks to the DB directly."""
from __future__ import annotations

import json
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models


# Users
def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(models.User.email == email.lower().strip()).first()


def create_user(db: Session, *, email: str, password_hash: str, display_name: str | None) -> models.User:
    u = models.User(email=email.lower().strip(), password_hash=password_hash, display_name=display_name)
    db.add(u)
    db.flush()
    return u


# Organizations
def create_organization(db: Session, *, name: str, owner: models.User) -> models.Organization:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())[:60].strip("-") or "org"
    for attempt in range(5):
        slug = base if attempt == 0 else f"{base}-{attempt + 1}"
        if db.query(models.Organization).filter_by(slug=slug).first():
            continue
        org = models.Organization(name=name.strip(), slug=slug)
        db.add(org)
        try:
            db.flush()
        except IntegrityError:
            # Lost a slug race with a concurrent insert — retry with next suffix.
            db.rollback()
            continue
        db.add(models.OrganizationMember(organization_id=org.id, user_id=owner.id, role="OWNER"))
        db.flush()
        return org
    # Extremely unlikely fallback: random suffix avoids an infinite loop.
    slug = f"{base}-{uuid.uuid4().hex[:8]}"
    org = models.Organization(name=name.strip(), slug=slug)
    db.add(org)
    db.flush()
    db.add(models.OrganizationMember(organization_id=org.id, user_id=owner.id, role="OWNER"))
    db.flush()
    return org


def list_user_orgs(db: Session, user_id: uuid.UUID) -> list[models.Organization]:
    rows = (
        db.query(models.Organization)
        .join(models.OrganizationMember, models.OrganizationMember.organization_id == models.Organization.id)
        .filter(models.OrganizationMember.user_id == user_id, models.Organization.is_deleted.is_(False))
        .all()
    )
    return rows


# Projects
def create_project(db: Session, *, org_id: uuid.UUID, data) -> models.Project:
    p = models.Project(
        organization_id=org_id,
        name=data.name,
        domain=data.domain,
        country=data.country.upper(),
        language=data.language,
        device=data.device,
        competitors=json.dumps(data.competitors or []),
    )
    db.add(p)
    db.flush()
    return p


def project_to_out(p: models.Project) -> dict:
    try:
        competitors = json.loads(p.competitors or "[]")
    except Exception:
        competitors = []
    return {
        "id": p.id,
        "organization_id": p.organization_id,
        "name": p.name,
        "domain": p.domain,
        "country": p.country,
        "language": p.language,
        "device": p.device,
        "competitors": competitors,
        "is_archived": p.is_archived,
    }
