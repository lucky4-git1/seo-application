"""Application services — business logic lives here, never in routes."""
from __future__ import annotations

import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app import repositories as repo
from app.schemas import normalize_domain
from app.security import audit, hash_password, verify_password, create_access_token


# ---- Auth ----
def register(db: Session, *, email: str, password: str, display_name: str | None) -> models.User:
    if repo.get_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = repo.create_user(db, email=email, password_hash=hash_password(password), display_name=display_name)
    audit(db, event="user.registered", user_id=user.id)
    db.commit()
    db.refresh(user)
    return user


def login(db: Session, *, email: str, password: str) -> tuple[models.User, str]:
    user = repo.get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token(user.id)
    audit(db, event="login", user_id=user.id)
    db.commit()
    return user, token


# ---- Projects (tenant-isolated: org membership verified by route dep) ----
def get_project_in_org(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> models.Project:
    p = db.get(models.Project, project_id)
    if p is None or p.organization_id != org_id or p.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return p
