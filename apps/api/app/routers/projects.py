from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas, services
from app import repositories as repo
from app.database import get_db
from app.security import audit, get_current_user, require_org_role

router = APIRouter(tags=["projects"])


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


@router.get("/organizations/{org_id}/projects")
def list_projects(org_id: uuid.UUID, user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _require_member(db, user.id, org_id)
    q = db.query(models.Project).filter(models.Project.organization_id == org_id, models.Project.is_deleted.is_(False))
    total = q.count()
    items = q.order_by(models.Project.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [repo.project_to_out(p) for p in items], "page": page, "page_size": page_size, "total": total}


@router.post("/organizations/{org_id}/projects", status_code=201)
def create_project(org_id: uuid.UUID, body: schemas.ProjectCreate, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    from app import entitlements
    entitlements.check_projects(db, org_id)
    p = repo.create_project(db, org_id=org_id, data=body)
    audit(db, event="project.created", user_id=user.id, org_id=org_id, details=p.name)
    db.commit()
    db.refresh(p)
    return repo.project_to_out(p)


@router.get("/organizations/{org_id}/projects/{project_id}")
def get_project(org_id: uuid.UUID, project_id: uuid.UUID, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    return repo.project_to_out(services.get_project_in_org(db, org_id, project_id))


@router.patch("/organizations/{org_id}/projects/{project_id}")
def update_project(org_id: uuid.UUID, project_id: uuid.UUID, body: schemas.ProjectUpdate, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_org_role(db, user.id, org_id, {"OWNER", "ADMIN"})
    p = services.get_project_in_org(db, org_id, project_id)
    if body.name is not None:
        p.name = body.name
    if body.country is not None:
        p.country = body.country.upper()
    if body.language is not None:
        p.language = body.language
    if body.device is not None:
        p.device = body.device
    if body.competitors is not None:
        if p.domain in body.competitors:
            raise HTTPException(status_code=400, detail="competitor cannot be your own domain")
        p.competitors = json.dumps(sorted(set(body.competitors)))
    if body.is_archived is not None:
        p.is_archived = body.is_archived
    audit(db, event="project.updated", user_id=user.id, org_id=org_id, details=str(project_id))
    db.commit()
    db.refresh(p)
    return repo.project_to_out(p)


@router.delete("/organizations/{org_id}/projects/{project_id}", status_code=204)
def delete_project(org_id: uuid.UUID, project_id: uuid.UUID, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_org_role(db, user.id, org_id, {"OWNER", "ADMIN"})
    p = services.get_project_in_org(db, org_id, project_id)
    p.is_deleted = True  # soft delete
    audit(db, event="project.deleted", user_id=user.id, org_id=org_id, details=str(project_id))
    db.commit()
