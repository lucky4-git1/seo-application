"""Security: Argon2 passwords, JWT sessions, request-scoped auth deps."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app import models

_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (Argon2Error, ValueError):
        # Wrong password, corrupt or legacy non-argon2 hashes (InvalidHashError
        # is a ValueError, not an Argon2Error) — all fail closed.
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, s.jwt_secret, algorithm=s.jwt_algorithm)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    s = get_settings()
    try:
        payload = jwt.decode(creds.credentials, s.jwt_secret, algorithms=[s.jwt_algorithm])
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(models.User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def require_org_role(db: Session, user_id: uuid.UUID, org_id: uuid.UUID, allowed: set[str]) -> models.OrganizationMember:
    m = (
        db.query(models.OrganizationMember)
        .filter(models.OrganizationMember.organization_id == org_id,
                models.OrganizationMember.user_id == user_id)
        .first()
    )
    if m is None or m.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return m


def audit(db: Session, *, event: str, user_id=None, org_id=None, details: str | None = None) -> None:
    db.add(models.AuditLog(event=event, user_id=user_id, organization_id=org_id, details=details))
