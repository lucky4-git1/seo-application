"""Audit evaluation service (Step 4, spec §14–§16).

run_audit(db, run_id): crawl pages → rule checks → AuditIssue +
AuditIssueInstance rows → bucket scores → health_score on the run.
seed_rules(db): idempotent upsert of RULES into audit_rules.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.audit import rules
from app.audit.rules import (
    BUCKET_WEIGHTS,
    CATEGORY_TO_BUCKET,
    MAX_STORED_INSTANCES,
    Ctx,
    health_score,
    rule_index,
    score_bucket,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def seed_rules(db: Session) -> int:
    """Upsert all RULES by code. Returns number of rules present."""
    existing = {r.code: r for r in db.query(seo.AuditRule).all()}
    for rule in rules.RULES:
        row = existing.get(rule.code)
        if row is None:
            db.add(seo.AuditRule(
                code=rule.code, name=rule.name, description=rule.description,
                severity=rule.severity, category=rule.category,
                recommendation=rule.recommendation, enabled=True))
        else:
            row.name = rule.name
            row.description = rule.description
            row.severity = rule.severity
            row.category = rule.category
            row.recommendation = rule.recommendation
    db.commit()
    return len(rules.RULES)


def build_ctx(db: Session, run_id) -> Ctx:
    pages = db.query(seo.CrawlPage).filter_by(crawl_run_id=run_id).all()
    links = db.query(seo.CrawlLink).filter_by(crawl_run_id=run_id).all()

    inbound: Counter = Counter()
    for link in links:
        if not link.is_internal:
            continue
        inbound[link.normalized_to_url] += 1

    # attach outbound internal links per source page for broken-link rule
    by_source: dict[str, list[dict]] = {}
    for link in links:
        by_source.setdefault(link.from_url, []).append(
            {"normalized_to_url": link.normalized_to_url,
             "status_code": link.status_code})

    dicts: list[dict] = []
    by_url: dict[str, dict] = {}
    ok_urls: set[str] = set()
    for p in pages:
        d = {
            "url": p.url, "normalized_url": p.normalized_url,
            "depth": p.depth, "status_code": p.status_code,
            "response_time_ms": p.response_time_ms,
            "title": p.title, "meta_description": p.meta_description,
            "canonical": p.canonical,
            "canonical_normalized": _norm_or_none(p.canonical),
            "robots_meta": p.robots_meta, "h1_count": p.h1_count,
            "word_count": p.word_count, "images_missing_alt": p.images_missing_alt,
            "is_noindex": p.is_noindex, "is_robots_blocked": p.is_robots_blocked,
            "schema_presence": p.schema_presence or [],
            "hreflang": p.hreflang or {},
            "content_hash": p.content_hash,
            "redirect_target_normalized": _norm_or_none(p.redirect_target),
            "out_links": by_source.get(p.url, []),
        }
        dicts.append(d)
        by_url[p.normalized_url] = d
        if p.status_code == 200:
            ok_urls.add(p.normalized_url)

    run = db.get(seo.CrawlRun, run_id)
    return Ctx(pages=dicts, inbound=inbound, by_url=by_url, ok_urls=ok_urls,
               run={"pages_crawled": run.pages_crawled if run else 0})


def _norm_or_none(url: str | None) -> str:
    if not url:
        return ""
    try:
        from app.crawler.normalize import normalize_url
        return normalize_url(url)
    except Exception:
        return ""


def run_audit(db: Session, run_id) -> dict:
    """Evaluate all enabled rules for a finished crawl run. Returns summary."""
    run = db.get(seo.CrawlRun, run_id)
    if run is None:
        raise ValueError(f"crawl run not found: {run_id}")
    n_rules = seed_rules(db)
    _ = n_rules
    db_rules = {r.code: r for r in db.query(seo.AuditRule).filter_by(enabled=True).all()}
    index = rule_index()
    ctx = build_ctx(db, run_id)
    now = utcnow()

    # replace previous results for idempotent re-runs
    old_ids = [i.id for i in db.query(seo.AuditIssue).filter_by(crawl_run_id=run_id).all()]
    if old_ids:
        db.query(seo.AuditIssueInstance).filter(
            seo.AuditIssueInstance.issue_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(seo.AuditIssue).filter_by(crawl_run_id=run_id).delete(
            synchronize_session=False)
        db.commit()

    per_bucket: dict[str, list[dict]] = {b: [] for b in BUCKET_WEIGHTS}
    counts = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "NOTICE": 0}
    total_instances = 0
    for code, db_rule in db_rules.items():
        rule = index.get(code)
        if rule is None:
            continue
        try:
            urls = sorted(set(rule.check(ctx)))
        except Exception:
            continue  # a rule must never break an audit run
        if not urls:
            continue
        issue = seo.AuditIssue(
            organization_id=run.organization_id, project_id=run.project_id,
            crawl_run_id=run_id, rule_id=db_rule.id, severity=rule.severity,
            category=rule.category, message=f"{rule.name} — {len(urls)} page(s) affected",
            why_it_matters=rule.description, recommendation=rule.recommendation,
            affected_count=len(urls), first_seen=now, last_seen=now)
        db.add(issue)
        db.flush()
        for u in urls[:MAX_STORED_INSTANCES]:
            db.add(seo.AuditIssueInstance(issue_id=issue.id, url=u, detected_at=now))
        counts[rule.severity] = counts.get(rule.severity, 0) + 1
        total_instances += len(urls)
        bucket = CATEGORY_TO_BUCKET.get(rule.category, "technical")
        per_bucket[bucket].append({"severity": rule.severity, "affected_count": len(urls)})
    db.commit()

    buckets = {b: score_bucket(per_bucket[b], ctx.run["pages_crawled"]) for b in BUCKET_WEIGHTS}
    score = health_score(buckets)
    run.issues_found = total_instances
    run.health_score = score
    db.commit()
    return {"run_id": str(run_id), "health_score": score, "buckets": buckets,
            "issue_rules": sum(counts.values()), "instances": total_instances,
            "by_severity": counts}
