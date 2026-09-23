from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app import repositories as repo
from app.database import get_db
from app.security import audit, get_current_user, require_org_role

router = APIRouter(tags=["organizations"])


@router.get("/organizations", response_model=list[schemas.OrganizationOut])
def list_orgs(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return repo.list_user_orgs(db, user.id)


@router.post("/organizations", response_model=schemas.OrganizationOut, status_code=201)
def create_org(body: schemas.OrganizationCreate, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = repo.create_organization(db, name=body.name, owner=user)
    audit(db, event="organization.created", user_id=user.id, org_id=org.id, details=org.name)
    db.commit()
    db.refresh(org)
    return org


@router.post("/organizations/{org_id}/members", status_code=201)
def add_member(org_id: uuid.UUID, body: schemas.MemberAdd, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None or org.is_deleted:
        raise HTTPException(status_code=404, detail="Organization not found")
    caller = require_org_role(db, user.id, org_id, {"OWNER", "ADMIN"})
    if body.role == "OWNER" and caller.role != "OWNER":
        raise HTTPException(status_code=403, detail="Only owners can grant OWNER")
    target = repo.get_user_by_email(db, str(body.email))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(models.OrganizationMember).filter_by(organization_id=org_id, user_id=target.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")
    db.add(models.OrganizationMember(organization_id=org_id, user_id=target.id, role=body.role))
    audit(db, event="team.member_added", user_id=user.id, org_id=org_id, details=f"{body.email}:{body.role}")
    db.commit()
    return {"ok": True}
