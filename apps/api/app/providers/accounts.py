"""Provider account management: encrypted credentials, status, test-connection.

Secrets are encrypted with app/providers/crypto.py before storage and never
returned in full — list/detail responses carry masked previews only.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.providers import crypto, registry
from app.providers.base import ProviderError


def utcnow() -> datetime:
    return datetime.now(UTC)


def list_supported() -> list[dict]:
    return [{"provider": k, **{kk: vv for kk, vv in v.items() if kk != "fields"},
             "fields": [{"name": f["name"], "label": f["label"], "secret": f["secret"]}
                        for f in v["fields"]]}
            for k, v in registry.PROVIDERS.items()]


def list_accounts(db: Session, org_id: uuid.UUID) -> list[dict]:
    rows = db.query(seo.ProviderAccount).filter_by(organization_id=org_id).all()
    return [_out(r) for r in rows]


def _out(row: seo.ProviderAccount) -> dict:
    try:
        creds = crypto.decrypt_credentials(row.credentials_enc)
    except ValueError:
        creds = {}
    return {"id": str(row.id), "provider": row.provider, "label": row.label,
            "credentials_masked": crypto.mask_credentials(creds),
            "status": row.status,
            "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
            "last_error": row.last_error}


def save_account(db: Session, org_id: uuid.UUID, provider: str, label: str,
                 credentials: dict) -> dict:
    if provider not in registry.PROVIDERS:
        raise KeyError(f"unknown provider: {provider}")
    registry.validate_credentials(provider, credentials)
    label = (label or "default").strip() or "default"
    row = (db.query(seo.ProviderAccount)
           .filter_by(organization_id=org_id, provider=provider, label=label).first())
    if row is None:
        row = seo.ProviderAccount(organization_id=org_id, provider=provider, label=label,
                                  credentials_enc="", status="CONFIGURED")
        db.add(row)
    row.credentials_enc = crypto.encrypt_credentials(credentials)
    row.status = "CONFIGURED"
    row.last_error = None
    db.commit()
    db.refresh(row)
    return _out(row)


def delete_account(db: Session, org_id: uuid.UUID, account_id: uuid.UUID) -> None:
    row = db.get(seo.ProviderAccount, account_id)
    if row is None or row.organization_id != org_id:
        raise KeyError("provider account not found")
    db.delete(row)
    db.commit()


def get_credentials(db: Session, org_id: uuid.UUID, provider: str,
                    label: str = "default") -> dict:
    """Decrypt credentials for internal use (never expose via API)."""
    row = (db.query(seo.ProviderAccount)
           .filter_by(organization_id=org_id, provider=provider, label=label).first())
    if row is None:
        raise KeyError(f"no {provider} account configured")
    return crypto.decrypt_credentials(row.credentials_enc)


def _set_status(db: Session, row: seo.ProviderAccount, status: str,
                error: str | None) -> None:
    row.status = status
    row.last_error = (error or "")[:1000] or None
    row.last_tested_at = utcnow()
    db.commit()


def test_connection(db: Session, org_id: uuid.UUID, provider: str,
                    label: str = "default") -> dict:
    """Live Test-Connection: cheapest real call per provider kind."""
    from app.providers.dataforseo import DataForSEOSERP

    row = (db.query(seo.ProviderAccount)
           .filter_by(organization_id=org_id, provider=provider, label=label).first())
    if row is None:
        raise KeyError(f"no {provider} account configured")
    try:
        creds = crypto.decrypt_credentials(row.credentials_enc)
    except ValueError as exc:
        _set_status(db, row, "INVALID", str(exc))
        return {"ok": False, "status": "INVALID", "error": str(exc)}
    try:
        if provider == "dataforseo":
            DataForSEOSERP(creds["login"], creds["password"]).search(
                "test", country="US", language="en", device="DESKTOP", depth=10)
        else:
            raise ProviderError(f"no test call implemented for {provider}")
    except ProviderError as exc:
        status = "INVALID" if exc.code in ("PROVIDER_AUTH",) else "ERROR"
        _set_status(db, row, status, str(exc))
        return {"ok": False, "status": status, "error": str(exc)}
    _set_status(db, row, "ACTIVE", None)
    return {"ok": True, "status": "ACTIVE"}


def record_usage(db: Session, org_id: uuid.UUID, provider: str, service: str,
                 operation: str, units: int = 1,
                 estimated_cost: float | None = None) -> None:
    db.add(seo.ProviderUsage(organization_id=org_id, provider=provider,
                             service=service, operation=operation, units=units,
                             estimated_cost=estimated_cost, created_at=utcnow()))
    db.commit()


def usage_summary(db: Session, org_id: uuid.UUID, days: int = 30) -> list[dict]:
    from datetime import timedelta

    from sqlalchemy import func
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    rows = (db.query(seo.ProviderUsage.provider, seo.ProviderUsage.service,
                     seo.ProviderUsage.operation,
                     func.sum(seo.ProviderUsage.units).label("units"),
                     func.count().label("calls"))
            .filter(seo.ProviderUsage.organization_id == org_id,
                    seo.ProviderUsage.created_at >= since)
            .group_by(seo.ProviderUsage.provider, seo.ProviderUsage.service,
                      seo.ProviderUsage.operation)
            .order_by(func.sum(seo.ProviderUsage.units).desc()).all())
    return [{"provider": p, "service": s, "operation": o, "units": int(u or 0),
             "calls": int(c or 0)} for p, s, o, u, c in rows]
