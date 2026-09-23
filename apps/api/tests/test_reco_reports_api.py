"""Steps 15–16 tests: recommendation collectors/scoring/status + reports."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient

import app.models
import app.models_seo as seo
from app.celery_app import celery
from app.database import (
    Base,
    get_engine,
    get_session_factory,
    override_engine_for_tests,
)
from app.main import app
from app.recommendations import priority

celery.conf.task_always_eager = True
override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)


def _setup(monkeypatch):
    from app import tasks as taskmod

    def fake_send(name, args=None, kwargs=None, **kw):
        fn = {"seo.recalculate": taskmod.recalculate_task,
              "seo.generate_report": taskmod.generate_report_task}[name]
        return fn.apply(args=list(args or []), kwargs=dict(kwargs or {}))

    monkeypatch.setattr(celery, "send_task", fake_send)


def _auth(email="reco@example.com"):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def test_priority_math():
    assert priority(10, 1.0, 0.5) == 100.0  # clamped
    assert priority(0, 1.0, 1.0) == 0.0
    assert priority(7, 0.9, 1.0) == 63.0
    assert priority(7, 0.9, 10.0) < priority(7, 0.9, 1.0)  # effort hurts


def _seed(db, org_id, proj_id):
    now = datetime.now(UTC)
    rule = db.query(seo.AuditRule).filter_by(code="TITLE_MISSING").first()
    if rule is None:
        rule = seo.AuditRule(code="TITLE_MISSING", name="Missing title",
                             description="d", severity="ERROR", category="Metadata",
                             recommendation="r")
        db.add(rule)
        db.commit()
    run = seo.CrawlRun(organization_id=org_id, project_id=proj_id, status="COMPLETED")
    db.add(run)
    db.commit()
    db.add(seo.AuditIssue(
        organization_id=org_id, project_id=proj_id, crawl_run_id=run.id,
        rule_id=rule.id, severity="ERROR", category="Metadata", message="m",
        why_it_matters="w", recommendation="r", affected_count=3,
        first_seen=now, last_seen=now))
    # GSC: striking-distance query (pos 8, low CTR, 2100 impr)
    conn = seo.GscConnection(organization_id=org_id, access_token_enc="x",
                             refresh_token_enc="y")
    db.add(conn)
    db.commit()
    prop = seo.GscProperty(connection_id=conn.id, project_id=proj_id,
                           site_url="https://reco-example.org/", is_selected=True)
    db.add(prop)
    db.commit()
    today = date.today()
    db.add(seo.GscQueryData(property_id=prop.id, date=today - timedelta(days=1),
                            query="buy shoes", clicks=5, impressions=2100,
                            ctr=0.002, position=8.0))
    # declining query: 100 clicks before, 40 now
    db.add(seo.GscQueryData(property_id=prop.id, date=today - timedelta(days=40),
                            query="old shoes", clicks=100, impressions=900,
                            ctr=0.11, position=6.0))
    db.add(seo.GscQueryData(property_id=prop.id, date=today - timedelta(days=1),
                            query="old shoes", clicks=40, impressions=800,
                            ctr=0.05, position=9.0))
    # keyword opportunity, untracked
    kw = seo.Keyword(organization_id=org_id, project_id=proj_id,
                     keyword="trail shoes", normalized_keyword="trail shoes")
    db.add(kw)
    db.commit()
    db.add(seo.KeywordMetric(keyword_id=kw.id, search_volume=20000, cpc=1.0,
                             competition=0.2, provider="test"))
    db.add(seo.KeywordIntent(keyword_id=kw.id, intent="TRANSACTIONAL",
                             confidence=0.8, method="heuristic"))
    # slipping tracked keyword
    t = seo.TrackedKeyword(organization_id=org_id, project_id=proj_id,
                           keyword="slip shoes", normalized_keyword="slip shoes")
    db.add(t)
    db.commit()
    db.add(seo.RankObservation(tracked_keyword_id=t.id,
                               observed_at=now - timedelta(days=2), rank=5,
                               ranking_url="https://reco-example.org/slip"))
    db.add(seo.RankObservation(tracked_keyword_id=t.id, observed_at=now, rank=12,
                               ranking_url="https://reco-example.org/slip"))
    # competitor gap: rival ranks #2, we are absent
    comp = seo.Competitor(organization_id=org_id, project_id=proj_id,
                          domain="rival.com", original_input="rival.com")
    db.add(comp)
    db.commit()
    t2 = seo.TrackedKeyword(organization_id=org_id, project_id=proj_id,
                            keyword="gap shoes", normalized_keyword="gap shoes")
    db.add(t2)
    db.commit()
    kw2 = seo.Keyword(organization_id=org_id, project_id=proj_id,
                      keyword="gap shoes", normalized_keyword="gap shoes")
    db.add(kw2)
    db.commit()
    db.add(seo.KeywordMetric(keyword_id=kw2.id, search_volume=80000, cpc=1.0,
                             competition=0.1, provider="test"))
    db.add(seo.KeywordIntent(keyword_id=kw2.id, intent="COMMERCIAL",
                             confidence=0.8, method="heuristic"))
    db.add(seo.SerpSearch(organization_id=org_id, project_id=proj_id,
                          keyword="gap shoes", cache_key=f"gap-{proj_id}",
                          provider="test", searched_at=now))
    db.commit()
    s = db.query(seo.SerpSearch).filter_by(project_id=proj_id).first()
    db.add(seo.SerpResult(serp_search_id=s.id, position=2, domain="rival.com",
                          url="https://rival.com/gap", result_type="organic"))
    db.commit()


def test_recalculate_collects_all_sources(monkeypatch):
    _setup(monkeypatch)
    h = _auth()
    org = client.post("/api/v1/organizations", json={"name": "ROrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "RP", "domain": "reco-example.org"},
                    headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    import uuid
    db = get_session_factory()()
    try:
        _seed(db, uuid.UUID(org["id"]), uuid.UUID(p["id"]))
    finally:
        db.close()

    r = client.post(f"{base}/recommendations/recalculate", headers=h)
    assert r.status_code == 202, r.text

    lst = client.get(f"{base}/recommendations", headers=h).json()
    sources = {i["source"] for i in lst["items"]}
    assert {"AUDIT", "GSC", "KEYWORDS", "RANK_TRACKING", "GAP"} <= sources, sources
    scores = [i["score"] for i in lst["items"]]
    assert scores == sorted(scores, reverse=True)  # default sort
    assert all(0 <= s <= 100 for s in scores)

    # status transition sticks
    first = lst["items"][0]
    r = client.patch(f"/api/v1/recommendations/{first['id']}",
                     json={"status": "DISMISSED"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "DISMISSED"

    # regeneration preserves the dismissal, replaces OPEN rows
    client.post(f"{base}/recommendations/recalculate", headers=h)
    lst2 = client.get(f"{base}/recommendations", headers=h).json()
    by_id = {i["id"]: i for i in lst2["items"]}
    assert by_id[first["id"]]["status"] == "DISMISSED"

    filt = client.get(f"{base}/recommendations",
                      params={"source": "GSC"}, headers=h).json()
    assert filt["items"] and all(i["source"] == "GSC" for i in filt["items"])


def test_reports_csv_and_pdf(monkeypatch):
    _setup(monkeypatch)
    h = _auth("reports@example.com")
    org = client.post("/api/v1/organizations", json={"name": "RepOrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "RepP", "domain": "rep-example.org"},
                    headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    import uuid
    db = get_session_factory()()
    try:
        _seed(db, uuid.UUID(org["id"]), uuid.UUID(p["id"]))
    finally:
        db.close()
    client.post(f"{base}/recommendations/recalculate", headers=h)

    for fmt in ("CSV", "PDF"):
        r = client.post(f"{base}/reports",
                        json={"type": "SEO_OVERVIEW", "format": fmt}, headers=h)
        assert r.status_code == 202, r.text
        rep_id, exp_id = r.json()["report"]["id"], r.json()["export"]["id"]
        lst = client.get(f"{base}/reports", headers=h).json()
        assert lst["items"][0]["status"] == "READY"
        dl = client.get(f"{base}/reports/exports/{exp_id}/download", headers=h)
        assert dl.status_code == 200
        if fmt == "CSV":
            assert dl.text.startswith("# Project")
            assert "rep-example.org" in dl.text
        else:
            assert dl.content[:4] == b"%PDF"
            assert len(dl.content) > 2000
        _ = rep_id
