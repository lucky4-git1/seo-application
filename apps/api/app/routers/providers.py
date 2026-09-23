"""Provider settings — supported vendors, account CRUD, test, usage."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.providers import accounts as provider_accounts
from app.security import get_current_user, require_org_role

router = APIRouter(tags=["providers"])


class ProviderSave(BaseModel):
    provider: str
    label: str = "default"
    credentials: dict


def _manager(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    # Only owners/admins touch credentials.
    require_org_role(db, user_id, org_id, {"OWNER", "ADMIN"})


@router.get("/providers")
def supported_providers(user: models.User = Depends(get_current_user)):
    return {"items": provider_accounts.list_supported()}


@router.get("/organizations/{org_id}/providers")
def list_provider_accounts(org_id: uuid.UUID,
                           user: models.User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    _manager(db, user.id, org_id)
    return {"items": provider_accounts.list_accounts(db, org_id)}


@router.post("/organizations/{org_id}/providers", status_code=201)
def save_provider_account(org_id: uuid.UUID, body: ProviderSave,
                          user: models.User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    _manager(db, user.id, org_id)
    try:
        return provider_accounts.save_account(db, org_id, body.provider,
                                              body.label, body.credentials)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/organizations/{org_id}/providers/{account_id}", status_code=204)
def delete_provider_account(org_id: uuid.UUID, account_id: uuid.UUID,
                            user: models.User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    _manager(db, user.id, org_id)
    try:
        provider_accounts.delete_account(db, org_id, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/organizations/{org_id}/providers/{account_id}/test")
def test_provider_account(org_id: uuid.UUID, account_id: uuid.UUID,
                          user: models.User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    from app import models_seo as seo
    _manager(db, user.id, org_id)
    row = db.get(seo.ProviderAccount, account_id)
    if row is None or row.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Provider account not found")
    try:
        return provider_accounts.test_connection(db, org_id, row.provider, row.label)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/organizations/{org_id}/usage")
def provider_usage(org_id: uuid.UUID,
                   user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   days: int = Query(30, ge=1, le=365)):
    _manager(db, user.id, org_id)
    return {"items": provider_accounts.usage_summary(db, org_id, days=days)}


@router.get("/organizations/{org_id}/limits")
def plan_limits(org_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    require_org_role(db, user.id, org_id, {"OWNER", "ADMIN", "MEMBER"})
    from app import entitlements
    return entitlements.usage_snapshot(db, org_id)
