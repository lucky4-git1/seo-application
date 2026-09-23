"""Competitor management + keyword gap from stored data.

Gap rows are computed live from real observations only:
- your rank = latest rank_observations per tracked keyword (null = unranked)
- competitor rank = latest stored serp_searches row for the same
  keyword/market containing the competitor domain (null = not found)

Nothing is estimated or fetched implicitly. If a competitor has no stored
SERP coverage, its cells are null — the UI says so plainly.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app import models_seo as seo
from app.database import get_db
from app.keywords import normalize_keyword
from app.schemas import DOMAIN_RE, normalize_domain
from app.security import get_current_user, require_org_role
from app.serp import find_rank
from app.services import get_project_in_org

router = APIRouter(tags=["competitors"])


class CompetitorIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    label: str | None = Field(default=None, max_length=200)


def _require_member(db: Session, user_id: uuid.UUID, org_id: uuid.UUID):
    return require_org_role(db, user_id, org_id, {"OWNER", "ADMIN", "MEMBER"})


def _comp_out(c: seo.Competitor) -> dict:
    return {"id": str(c.id), "domain": c.domain, "label": c.label,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None}


@router.post("/organizations/{org_id}/projects/{project_id}/competitors",
             status_code=201)
def add_competitor(org_id: uuid.UUID, project_id: uuid.UUID, body: CompetitorIn,
                   user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    domain = normalize_domain(body.domain)
    if not DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail="invalid domain")
    if domain == project.domain:
        raise HTTPException(status_code=400, detail="competitor cannot be your own domain")
    existing = (db.query(seo.Competitor)
                .filter_by(project_id=project.id, domain=domain).first())
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.label = body.label or existing.label
            db.commit()
        return _comp_out(existing)
    row = seo.Competitor(organization_id=org_id, project_id=project.id,
                         domain=domain, original_input=body.domain.strip(),
                         label=body.label)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _comp_out(row)


@router.get("/organizations/{org_id}/projects/{project_id}/competitors")
def list_competitors(org_id: uuid.UUID, project_id: uuid.UUID,
                     user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db),
                     active_only: bool = Query(True)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    q = db.query(seo.Competitor).filter_by(project_id=project.id)
    if active_only:
        q = q.filter_by(is_active=True)
    return {"items": [_comp_out(c) for c in q.order_by(seo.Competitor.domain).all()]}


@router.delete("/organizations/{org_id}/projects/{project_id}/competitors/{comp_id}",
               status_code=204)
def remove_competitor(org_id: uuid.UUID, project_id: uuid.UUID, comp_id: uuid.UUID,
                      user: models.User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    row = db.get(seo.Competitor, comp_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="Competitor not found")
    row.is_active = False
    db.commit()


def _latest_serp_for(db: Session, project_id: uuid.UUID, keyword_norm: str,
                     country: str, device: str) -> seo.SerpSearch | None:
    cands = (db.query(seo.SerpSearch).filter_by(project_id=project_id).all())
    best = None
    for s in cands:
        if normalize_keyword(s.keyword) != keyword_norm:
            continue
        if s.country != country or s.device != device:
            continue
        if best is None or (s.searched_at and best.searched_at and
                            s.searched_at > best.searched_at):
            best = s
    return best


@router.get("/organizations/{org_id}/projects/{project_id}/competitors/{comp_id}/overview")
def competitor_overview(org_id: uuid.UUID, project_id: uuid.UUID, comp_id: uuid.UUID,
                        user: models.User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    comp = db.get(seo.Competitor, comp_id)
    if comp is None or comp.project_id != project.id:
        raise HTTPException(status_code=404, detail="Competitor not found")
    appearances = 0
    rank_sum = 0
    top_pages: dict[str, dict] = {}
    for s in db.query(seo.SerpSearch).filter_by(project_id=project.id).all():
        rank, url = find_rank(s.results, comp.domain)
        if rank is None:
            continue
        appearances += 1
        rank_sum += rank
        if url:
            entry = top_pages.setdefault(url, {"url": url, "keywords": 0,
                                               "best_rank": rank})
            entry["keywords"] += 1
            entry["best_rank"] = min(entry["best_rank"], rank)
    pages = sorted(top_pages.values(), key=lambda p: (-p["keywords"], p["best_rank"]))[:20]
    return {"competitor": _comp_out(comp),
            "serp_appearances": appearances,
            "avg_position": round(rank_sum / appearances, 1) if appearances else None,
            "top_pages": pages}


@router.get("/organizations/{org_id}/projects/{project_id}/keyword-gap")
def keyword_gap(org_id: uuid.UUID, project_id: uuid.UUID,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db),
                competitor_id: uuid.UUID | None = Query(None),
                bucket: str | None = Query(None, pattern="^(missing|weak|shared|strong)$"),
                intent: str | None = Query(None),
                min_volume: int | None = Query(None, ge=0),
                max_difficulty: float | None = Query(None, ge=0, le=100),
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require_member(db, user.id, org_id)
    project = get_project_in_org(db, org_id, project_id)
    comps = db.query(seo.Competitor).filter_by(project_id=project.id,
                                               is_active=True).all()
    if competitor_id:
        comps = [c for c in comps if c.id == competitor_id]
        if not comps:
            raise HTTPException(status_code=404, detail="Competitor not found")
    from app.gap import compute_gap

    result = compute_gap(db, project, comps, bucket=bucket, intent=intent,
                         min_volume=min_volume, max_difficulty=max_difficulty,
                         page=page, page_size=page_size)
    result["competitors"] = [_comp_out(c) for c in comps]
    return result


@router.get("/organizations/{org_id}/projects/{project_id}/keyword-gap/export")
def keyword_gap_export(org_id: uuid.UUID, project_id: uuid.UUID,
                       user: models.User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    import csv
    import io

    from fastapi.responses import PlainTextResponse
    # Reuse the same computation by calling through with a large page.
    data = keyword_gap(org_id, project_id, user, db, None, None, None, None,
                       None, 1, 5000)
    buf = io.StringIO()
    w = csv.writer(buf)
    comp_ids = [c["id"] for c in data["competitors"]]
    w.writerow(["keyword", "your_rank", "bucket", "volume", "difficulty",
                "intent", "opportunity",
                *[f"comp_{cid[:8]}" for cid in comp_ids]])
    for r in data["items"]:
        w.writerow([r["keyword"], r["your_rank"], r["bucket"], r["search_volume"],
                    r["difficulty"], r["intent"], r["opportunity"],
                    *[r["competitor_ranks"].get(cid) for cid in comp_ids]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=keyword-gap.csv"})
