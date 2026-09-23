"""Centralized recommendation engine (Step 15, spec §32–§33).

Collectors turn stored module data (audit issues, GSC history, keyword
scores, rank movements, keyword gap) into Recommendation rows. Priority:

    score = impact(0–10) × confidence(0–1) × 10 / effort(0.5–5), clamped 0–100

For keyword-derived recos impact comes from the opportunity score
(impact = opportunity/10), tying prioritization to measured upside.

Regeneration replaces OPEN rows only — human decisions (IN_PROGRESS,
DISMISSED, COMPLETED) are never overwritten.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models_seo as seo
from app.models import Project


def utcnow() -> datetime:
    return datetime.now(UTC)


SEVERITY_IMPACT = {"CRITICAL": 9.0, "ERROR": 7.0, "WARNING": 4.0, "NOTICE": 2.0}
CATEGORY_EFFORT = {
    "Metadata": 1.0, "Content": 3.0, "Links": 2.0, "Images": 1.0,
    "Canonical": 2.0, "Redirects": 2.0, "HTTPS": 2.0, "Structured Data": 2.0,
    "Crawlability": 2.5, "Indexability": 2.0, "Performance": 4.0,
    "International": 2.5,
}


def priority(impact: float, confidence: float, effort: float) -> float:
    effort = max(0.5, min(5.0, effort or 1.0))
    return round(max(0.0, min(100.0, impact * confidence * 10.0 / effort)), 1)


def _add(db: Session, org_id, proj_id, *, type: str, source: str, severity: str,
         impact: float, effort: float, confidence: float, title: str,
         description: str, why: str, action: str,
         related_url: str | None = None,
         related_keyword: str | None = None) -> seo.Recommendation:
    row = seo.Recommendation(
        organization_id=org_id, project_id=proj_id, type=type, source=source,
        severity=severity, impact=impact, effort=effort, confidence=confidence,
        score=priority(impact, confidence, effort), title=title,
        description=description, why=why, recommended_action=action,
        related_url=(related_url or "")[:2000] or None,
        related_keyword=related_keyword, status="OPEN")
    db.add(row)
    return row


def collect_audit(db: Session, org_id, proj_id) -> int:
    """Latest completed audit's firing rules → technical recos (top 15)."""
    run = (db.query(seo.CrawlRun).filter_by(project_id=proj_id, status="COMPLETED")
           .order_by(seo.CrawlRun.created_at.desc()).first())
    if run is None:
        return 0
    issues = (db.query(seo.AuditIssue)
              .filter_by(crawl_run_id=run.id)
              .order_by(seo.AuditIssue.affected_count.desc()).limit(15).all())
    n = 0
    for issue in issues:
        _add(db, org_id, proj_id, type="TECHNICAL", source="AUDIT",
             severity=issue.severity,
             impact=SEVERITY_IMPACT.get(issue.severity, 3.0),
             effort=CATEGORY_EFFORT.get(issue.category, 2.0),
             confidence=0.9, title=f"{issue.message}",
             description=issue.message, why=issue.why_it_matters,
             action=issue.recommendation,
             related_url=None)
        n += 1
    return n


def collect_gsc(db: Session, org_id, proj_id) -> int:
    """GSC opportunities: striking-distance + low-CTR + decliners."""
    prop = (db.query(seo.GscProperty)
            .filter_by(project_id=proj_id, is_selected=True).first())
    if prop is None:
        return 0
    n = 0
    # striking distance: positions 4–15 with real impressions
    rows = (db.query(seo.GscQueryData.query,
                     func.sum(seo.GscQueryData.clicks).label("clicks"),
                     func.sum(seo.GscQueryData.impressions).label("impr"),
                     func.avg(seo.GscQueryData.position).label("pos"))
            .filter(seo.GscQueryData.property_id == prop.id)
            .group_by(seo.GscQueryData.query).having(func.avg(seo.GscQueryData.position) >= 4)
            .having(func.avg(seo.GscQueryData.position) <= 15)
            .having(func.sum(seo.GscQueryData.impressions) >= 500)
            .order_by(func.sum(seo.GscQueryData.impressions).desc()).limit(10).all())
    for query, clicks, impr, pos in rows:
        clicks, impr = int(clicks or 0), int(impr or 0)
        ctr = clicks / impr if impr else 0.0
        if ctr >= 0.05:
            continue
        _add(db, org_id, proj_id, type="CONTENT", source="GSC", severity="WARNING",
             impact=7.0, effort=2.0, confidence=0.75,
             title=f"Striking-distance query needs CTR work: {query}",
             description=(f"Position {pos:.1f} with {impr:,} impressions but "
                          f"{ctr:.1%} CTR."),
             why="Page-one proximity with visibility but no clicks means the snippet loses.",
             action=("Rewrite the title/meta to match the query intent and add the "
                     "exact query near the top of the page."),
             related_keyword=query)
        n += 1
    # decliners: clicks down ≥30% over last 28d vs prior 28d
    today = date.today()
    recent = today - timedelta(days=28)
    older = today - timedelta(days=56)
    rq = (db.query(seo.GscQueryData.query,
                   func.sum(seo.GscQueryData.clicks).label("clicks"))
          .filter(seo.GscQueryData.property_id == prop.id,
                  seo.GscQueryData.date >= recent)
          .group_by(seo.GscQueryData.query).all())
    oq = dict(db.query(seo.GscQueryData.query,
                       func.sum(seo.GscQueryData.clicks))
              .filter(seo.GscQueryData.property_id == prop.id,
                      seo.GscQueryData.date >= older,
                      seo.GscQueryData.date < recent)
              .group_by(seo.GscQueryData.query).all())
    declined = sorted(
        ((q, int(c or 0), int(oq.get(q) or 0)) for q, c in rq if (oq.get(q) or 0) >= 50),
        key=lambda t: (t[1] - t[2]))[:10]
    for query, now_c, was_c in declined:
        if was_c and (was_c - now_c) / was_c >= 0.3:
            _add(db, org_id, proj_id, type="CONTENT", source="GSC",
                 severity="WARNING", impact=6.0, effort=3.0, confidence=0.65,
                 title=f"Declining query needs attention: {query}",
                 description=f"Clicks fell from {was_c:,} to {now_c:,} in 28 days.",
                 why="Sustained click decay usually means lost relevance or fresh competition.",
                 action=("Check the ranking URL, refresh the content, and inspect "
                         "SERP changes for new competitors/features."),
                 related_keyword=query)
            n += 1
    return n


def collect_keywords(db: Session, org_id, proj_id) -> int:
    """High-opportunity keywords with no tracked rank → content recos."""
    from app.keyword_service import scored_view
    kws = db.query(seo.Keyword).filter_by(organization_id=org_id).limit(500).all()
    cands = []
    for kw in kws:
        if kw.project_id not in (None, proj_id):
            continue
        v = scored_view(db, kw)
        if (v["opportunity"] or 0) >= 40 and (v["search_volume"] or 0) >= 500:
            tracked = (db.query(seo.TrackedKeyword)
                       .filter_by(project_id=proj_id,
                                  normalized_keyword=kw.normalized_keyword).first())
            if tracked is None:
                cands.append((v["opportunity"], kw, v))
    cands.sort(reverse=True)
    n = 0
    for opp, kw, v in cands[:10]:
        _add(db, org_id, proj_id, type="CONTENT", source="KEYWORDS",
             severity="NOTICE", impact=round(opp / 10, 1), effort=3.0,
             confidence=0.6,
             title=f"Content opportunity: {kw.keyword}",
             description=(f"Opportunity {opp:.0f}, volume {v['search_volume']:,}, "
                          f"difficulty {v['difficulty']}, intent {v['intent']}."),
             why="Demand exists and difficulty is achievable, but nothing targets it.",
             action=("Publish or expand a page targeting this keyword and add it "
                     "to position tracking."),
             related_keyword=kw.keyword)
        n += 1
    return n


def collect_ranks(db: Session, org_id, proj_id) -> int:
    """Tracked keywords that slipped ≥3 positions → ranking recos."""
    from app.tracking import movement
    tracked = (db.query(seo.TrackedKeyword)
               .filter_by(project_id=proj_id, is_active=True).all())
    n = 0
    for t in tracked:
        m = movement(db, t)
        if (m["change"] is not None and m["change"] <= -3
                and m["current_rank"] is not None):
            _add(db, org_id, proj_id, type="RANKING", source="RANK_TRACKING",
                 severity="WARNING", impact=6.5, effort=2.5, confidence=0.7,
                 title=f"Ranking slipped for: {t.keyword}",
                 description=(f"Now #{m['current_rank']} (was #{m['previous_rank']})."),
                 why="Fresh drops are cheapest to reverse while relevance persists.",
                 action=("Re-check intent fit, internal links, and the current "
                         "winner's content, then refresh the page."),
                 related_keyword=t.keyword,
                 related_url=m["current_url"])
            n += 1
    return n


def collect_competitors(db: Session, org_id, proj_id) -> int:
    """Top missing/weak gap rows → competitor recos."""
    from app.gap import compute_gap

    project = db.get(Project, proj_id)
    if project is None:
        return 0
    comps = db.query(seo.Competitor).filter_by(project_id=proj_id,
                                               is_active=True).all()
    try:
        data = compute_gap(db, project, comps, page=1, page_size=25)
    except Exception:
        return 0
    n = 0
    for r in data["items"]:
        if r["bucket"] not in ("missing", "weak"):
            continue
        if (r["opportunity"] or 0) < 50:
            continue
        _add(db, org_id, proj_id, type="COMPETITOR", source="GAP",
             severity="NOTICE", impact=round((r["opportunity"] or 50) / 10, 1),
             effort=3.0, confidence=0.55,
             title=f"Close the gap on: {r['keyword']}",
             description=(f"Competitors rank #{min([v for v in r['competitor_ranks'].values() if v] or [0])} "
                          f"while you are at #{r['your_rank'] or '–'}."),
             why="Competitors convert demand you are invisible for.",
             action="Build a better page for this keyword than the ranking competitor.",
             related_keyword=r["keyword"])
        n += 1
        if n >= 10:
            break
    return n


def recalculate(db: Session, org_id, proj_id) -> dict:
    """Replace OPEN recos with a fresh pass. Returns counts per source."""
    db.query(seo.Recommendation).filter_by(project_id=proj_id,
                                           status="OPEN").delete()
    db.commit()
    counts = {
        "audit": collect_audit(db, org_id, proj_id),
        "gsc": collect_gsc(db, org_id, proj_id),
        "keywords": collect_keywords(db, org_id, proj_id),
        "ranks": collect_ranks(db, org_id, proj_id),
        "competitors": collect_competitors(db, org_id, proj_id),
    }
    db.commit()
    counts["total"] = sum(counts.values())
    return counts
