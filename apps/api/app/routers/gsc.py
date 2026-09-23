"""Google Search Console: OAuth connect, properties, sync jobs, analytics reads."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import gsc as gsc_service
from app import jobs as jobstore
from app import models
from app import models_seo as seo
from app.database import get_db
from app.providers import crypto, google
from app.providers.base import ProviderError
from app.ratelimit import EXPENSIVE_LIMIT, limiter
from app.security import get_current_user, require_org_role
from app.services import get_project_in_org

router = APIRouter(tags=["gsc"])


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _selected_property(db: Session, project_id: uuid.UUID) -> seo.GscProperty | None:
    return (db.query(seo.GscProperty)
            .filter_by(project_id=project_id, is_selected=True).first())


def _resolve_property(db: Session, project_id: uuid.UUID,
                      property_id: uuid.UUID | None) -> seo.GscProperty:
    if property_id:
        prop = db.get(seo.GscProperty, property_id)
        if prop is None or prop.project_id != project_id:
            raise HTTPException(status_code=404, detail="GSC property not found")
        return prop
    prop = _selected_property(db, project_id)
    if prop is None:
        raise HTTPException(status_code=400,
                            detail="No Search Console property selected for this project")
    return prop


class SelectPropertyIn(BaseModel):
    property_id: uuid.UUID


class SyncIn(BaseModel):
    property_id: uuid.UUID | None = None
    days: int = Field(default=90, ge=7, le=365)


@router.get("/organizations/{org_id}/projects/{project_id}/gsc/auth-url")
def gsc_auth_url(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    get_project_in_org(db, org_id, project_id)
    try:
        url = google.authorization_url(str(org_id), str(project_id), str(user.id))
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"auth_url": url}


@router.get("/gsc/oauth/callback")
def gsc_oauth_callback(request: Request, code: str | None = Query(None),
                       state: str | None = Query(None),
                       error: str | None = Query(None),
                       db: Session = Depends(get_db)):
    """Google redirects here. HTML for humans, JSON for API clients."""
    wants_json = "application/json" in (request.headers.get("accept") or "")

    def respond(status: int, payload: dict):
        if wants_json:
            return JSONResponse(status_code=status, content=payload)
        if status == 200:
            props = "".join(f"<li>{p}</li>" for p in payload.get("properties", []))
            html = (f"<html><body style='font-family:sans-serif'>"
                    f"<h2>Search Console connected</h2>"
                    f"<p>Account: {payload.get('account', '')}</p>"
                    f"<p>Properties found:</p><ul>{props}</ul>"
                    f"<p>You can close this tab and return to the app.</p>"
                    f"</body></html>")
            return HTMLResponse(content=html, status_code=200)
        return HTMLResponse(
            content=f"<html><body><h2>Connection failed</h2><p>{payload.get('detail', '')}</p>"
                    f"</body></html>", status_code=status)

    if error:
        return respond(400, {"detail": f"Google OAuth error: {error}"})
    if not code or not state:
        return respond(400, {"detail": "Missing code/state"})
    try:
        st = google.parse_state_token(state)
    except ProviderError as exc:
        return respond(400, {"detail": str(exc)})
    org_id = uuid.UUID(st["org"])
    try:
        tokens = google.exchange_code(code)
    except ProviderError as exc:
        return respond(502, {"detail": str(exc)})
    conn = gsc_service.save_connection(db, org_id, tokens)
    try:
        props = gsc_service.refresh_properties(db, conn)
    except ProviderError as exc:
        return respond(502, {"detail": str(exc)})
    return respond(200, {"connection_id": str(conn.id),
                         "properties": [p.site_url for p in props]})


@router.get("/organizations/{org_id}/projects/{project_id}/gsc/connections")
def gsc_connections(org_id: uuid.UUID, project_id: uuid.UUID,
                    user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    get_project_in_org(db, org_id, project_id)
    rows = db.query(seo.GscConnection).filter_by(organization_id=org_id).all()
    return {"items": [{
        "id": str(c.id), "google_account": c.google_account, "status": c.status,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "properties": [{"id": str(p.id), "site_url": p.site_url,
                        "property_type": p.property_type,
                        "project_id": str(p.project_id) if p.project_id else None,
                        "is_selected": p.is_selected,
                        "last_synced_at": p.last_synced_at.isoformat()
                        if p.last_synced_at else None}
                       for p in c.properties],
    } for c in rows]}


@router.post("/organizations/{org_id}/projects/{project_id}/gsc/select")
def gsc_select(org_id: uuid.UUID, project_id: uuid.UUID, body: SelectPropertyIn,
               user: models.User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    prop = db.get(seo.GscProperty, body.property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="GSC property not found")
    conn = db.get(seo.GscConnection, prop.connection_id)
    if conn is None or conn.organization_id != org_id:
        raise HTTPException(status_code=404, detail="GSC property not found")
    (db.query(seo.GscProperty).filter_by(project_id=project.id)
     .update({"is_selected": False}))
    prop.project_id = project.id
    prop.is_selected = True
    db.commit()
    return {"id": str(prop.id), "site_url": prop.site_url, "is_selected": True}


@router.post("/organizations/{org_id}/projects/{project_id}/gsc/sync",
             status_code=202)
@limiter.limit(EXPENSIVE_LIMIT)
def gsc_sync(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, body: SyncIn,
             user: models.User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    from app.celery_app import celery

    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    prop = _resolve_property(db, project.id, body.property_id)
    job = jobstore.create_job(db, organization_id=org_id, project_id=project.id,
                              job_type="SYNC_GSC",
                              payload={"property_id": str(prop.id), "days": body.days})
    db.commit()
    celery.send_task("seo.sync_gsc", args=[str(job.id)],
                     kwargs={"property_id": str(prop.id), "days": body.days})
    return {"job": {"id": str(job.id), "status": job.status, "job_type": job.job_type},
            "property_id": str(prop.id)}


def _date_floor(days: int):
    return date.today() - timedelta(days=max(1, min(days, 365)))


@router.get("/organizations/{org_id}/projects/{project_id}/gsc/overview")
def gsc_overview(org_id: uuid.UUID, project_id: uuid.UUID,
                 user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db),
                 property_id: uuid.UUID | None = Query(None),
                 days: int = Query(28, ge=1, le=365)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    prop = _resolve_property(db, project.id, property_id)
    since = _date_floor(days)

    def totals(model, group_col):
        rows = (db.query(
            func.sum(model.clicks).label("clicks"),
            func.sum(model.impressions).label("impressions"),
            func.avg(model.position).label("position"))
            .filter(model.property_id == prop.id, model.date >= since).all())
        clicks = int(rows[0][0] or 0)
        impr = int(rows[0][1] or 0)
        return {"clicks": clicks, "impressions": impr,
                "ctr": round(clicks / impr, 4) if impr else 0.0,
                "avg_position": round(float(rows[0][2] or 0), 1)}

    daily_q = (db.query(seo.GscQueryData.date,
                        func.sum(seo.GscQueryData.clicks).label("clicks"),
                        func.sum(seo.GscQueryData.impressions).label("impressions"))
               .filter(seo.GscQueryData.property_id == prop.id,
                       seo.GscQueryData.date >= since)
               .group_by(seo.GscQueryData.date).order_by(seo.GscQueryData.date).all())
    return {
        "property": {"id": str(prop.id), "site_url": prop.site_url,
                     "last_synced_at": prop.last_synced_at.isoformat()
                     if prop.last_synced_at else None},
        "queries": totals(seo.GscQueryData, seo.GscQueryData.query),
        "pages": totals(seo.GscPageData, seo.GscPageData.page),
        "daily": [{"date": d.isoformat(), "clicks": int(c or 0),
                   "impressions": int(i or 0)} for d, c, i in daily_q],
    }


@router.get("/organizations/{org_id}/projects/{project_id}/gsc/queries")
def gsc_queries(org_id: uuid.UUID, project_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db),
                property_id: uuid.UUID | None = Query(None),
                days: int = Query(28, ge=1, le=365),
                search: str | None = Query(None),
                sort: str = Query("impressions",
                                  pattern="^(clicks|impressions|ctr|position|query)$"),
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    prop = _resolve_property(db, project.id, property_id)
    since = _date_floor(days)
    q = (db.query(seo.GscQueryData.query,
                  func.sum(seo.GscQueryData.clicks).label("clicks"),
                  func.sum(seo.GscQueryData.impressions).label("impressions"),
                  func.avg(seo.GscQueryData.position).label("position"))
         .filter(seo.GscQueryData.property_id == prop.id,
                 seo.GscQueryData.date >= since))
    if search:
        q = q.filter(seo.GscQueryData.query.ilike(f"%{search}%"))
    q = q.group_by(seo.GscQueryData.query)
    sorters = {"clicks": func.sum(seo.GscQueryData.clicks).desc(),
               "impressions": func.sum(seo.GscQueryData.impressions).desc(),
               "ctr": (func.sum(seo.GscQueryData.clicks) * 1.0
                       / func.nullif(func.sum(seo.GscQueryData.impressions), 0)).desc(),
               "position": func.avg(seo.GscQueryData.position).asc(),
               "query": seo.GscQueryData.query.asc()}
    q = q.order_by(sorters[sort])
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for query, clicks, impr, pos in rows:
        clicks, impr = int(clicks or 0), int(impr or 0)
        items.append({"query": query, "clicks": clicks, "impressions": impr,
                      "ctr": round(clicks / impr, 4) if impr else 0.0,
                      "position": round(float(pos or 0), 1)})
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/organizations/{org_id}/projects/{project_id}/gsc/pages")
def gsc_pages(org_id: uuid.UUID, project_id: uuid.UUID,
              user: models.User = Depends(get_current_user),
              db: Session = Depends(get_db),
              property_id: uuid.UUID | None = Query(None),
              days: int = Query(28, ge=1, le=365),
              search: str | None = Query(None),
              sort: str = Query("impressions",
                                pattern="^(clicks|impressions|ctr|position|page)$"),
              page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    prop = _resolve_property(db, project.id, property_id)
    since = _date_floor(days)
    q = (db.query(seo.GscPageData.page,
                  func.sum(seo.GscPageData.clicks).label("clicks"),
                  func.sum(seo.GscPageData.impressions).label("impressions"),
                  func.avg(seo.GscPageData.position).label("position"))
         .filter(seo.GscPageData.property_id == prop.id,
                 seo.GscPageData.date >= since))
    if search:
        q = q.filter(seo.GscPageData.page.ilike(f"%{search}%"))
    q = q.group_by(seo.GscPageData.page)
    sorters = {"clicks": func.sum(seo.GscPageData.clicks).desc(),
               "impressions": func.sum(seo.GscPageData.impressions).desc(),
               "ctr": (func.sum(seo.GscPageData.clicks) * 1.0
                       / func.nullif(func.sum(seo.GscPageData.impressions), 0)).desc(),
               "position": func.avg(seo.GscPageData.position).asc(),
               "page": seo.GscPageData.page.asc()}
    q = q.order_by(sorters[sort])
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for pg, clicks, impr, pos in rows:
        clicks, impr = int(clicks or 0), int(impr or 0)
        items.append({"page": pg, "clicks": clicks, "impressions": impr,
                      "ctr": round(clicks / impr, 4) if impr else 0.0,
                      "position": round(float(pos or 0), 1)})
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.delete("/organizations/{org_id}/projects/{project_id}/gsc/connections/{conn_id}",
               status_code=204)
def gsc_disconnect(org_id: uuid.UUID, project_id: uuid.UUID, conn_id: uuid.UUID,
                   user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    require_org_role(db, user.id, org_id, {"OWNER", "ADMIN"})
    get_project_in_org(db, org_id, project_id)
    conn = db.get(seo.GscConnection, conn_id)
    if conn is None or conn.organization_id != org_id:
        raise HTTPException(status_code=404, detail="GSC connection not found")
    # tombstone tokens before cascade delete removes properties + data
    conn.access_token_enc = crypto.encrypt_credentials({"token": "revoked"})
    conn.refresh_token_enc = crypto.encrypt_credentials({"token": "revoked"})
    conn.status = "REVOKED"
    db.commit()
    db.delete(conn)
    db.commit()
