"""SQLAlchemy engine / session. Supports Postgres (prod) and SQLite (tests)."""
from __future__ import annotations

from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def _build_engine(url: str):
    connect_args = {}
    poolclass = None
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        connect_args = {"check_same_thread": False}
        # In-memory SQLite must share one connection, else tables vanish per-connection.
        if url in ("sqlite://", "sqlite:///:memory:"):
            poolclass = StaticPool
    if poolclass:
        return create_engine(url, pool_pre_ping=True, connect_args=connect_args, poolclass=poolclass)
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings().database_url)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---- test helper: allow overriding engine ----
def override_engine_for_tests(url: str = "sqlite://"):
    from sqlalchemy import event

    global _engine, _SessionLocal
    _engine = _build_engine(url)
    if url.startswith("sqlite"):
        # Enforce FK cascades like Postgres does, so cascade tests are honest.
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return _engine
