"""Liveness + readiness. Readiness checks DB and Redis without leaking details."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    checks = {"api": True, "database": False, "redis": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    try:
        import redis

        from app.config import get_settings
        r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
        try:
            r.ping()
            checks["redis"] = True
        finally:
            r.close()
    except Exception:
        pass
    ok = checks["database"]  # redis optional for phase-1 readiness
    return {"ready": ok, "checks": checks}
