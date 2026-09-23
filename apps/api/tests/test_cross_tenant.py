"""Step-19: cross-tenant isolation across every new module router.

User B (no membership in org A) must get 403/404 on all of A's project
resources — never data, never existence oracle beyond the gate.
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from datetime import UTC

from fastapi.testclient import TestClient

import app.models
import app.models_seo as seo
from app.database import (
    Base,
    get_engine,
    get_session_factory,
    override_engine_for_tests,
)
from app.main import app

override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)


def _auth(email):
    client.post("/api/v1/auth/register",
                json={"email": email, "password": "password123"})
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def _seed_owner_data():
    """Owner A with project + one row in each module table. Returns ids."""
    import uuid
    from datetime import datetime
    h = _auth("tenant-a@example.com")
    org = client.post("/api/v1/organizations", json={"name": "TOrgA"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "TP", "domain": "tenant-a-example.org"},
                    headers=h).json()
    db = get_session_factory()()
    try:
        oid, pid = uuid.UUID(org["id"]), uuid.UUID(p["id"])
        run = seo.CrawlRun(organization_id=oid, project_id=pid, status="COMPLETED")
        db.add(run)
        db.commit()
        rule = seo.AuditRule(code="T_CTA", name="T", description="d",
                             severity="ERROR", category="Metadata",
                             recommendation="r")
        db.add(rule)
        db.commit()
        now = datetime.now(UTC)
        issue = seo.AuditIssue(
            organization_id=oid, project_id=pid, crawl_run_id=run.id,
            rule_id=rule.id, severity="ERROR", category="Metadata",
            message="m", why_it_matters="w", recommendation="r",
            affected_count=1, first_seen=now, last_seen=now)
        db.add(issue)
        db.commit()
        s = seo.SerpSearch(organization_id=oid, project_id=pid, keyword="kw",
                           cache_key=f"ct-{pid}", provider="test",
                           searched_at=now)
        db.add(s)
        db.commit()
        t = seo.TrackedKeyword(organization_id=oid, project_id=pid,
                               keyword="kw", normalized_keyword="kw")
        db.add(t)
        db.commit()
        kw = seo.Keyword(organization_id=oid, project_id=pid, keyword="kw",
                         normalized_keyword="kw")
        db.add(kw)
        db.commit()
        comp = seo.Competitor(organization_id=oid, project_id=pid,
                              domain="rival.com", original_input="rival.com")
        db.add(comp)
        db.commit()
        conn = seo.GscConnection(organization_id=oid, access_token_enc="x",
                                 refresh_token_enc="y")
        db.add(conn)
        db.commit()
        prop = seo.GscProperty(connection_id=conn.id, project_id=pid,
                               site_url="https://tenant-a-example.org/",
                               is_selected=True)
        db.add(prop)
        db.commit()
        reco = seo.Recommendation(
            organization_id=oid, project_id=pid, type="TECHNICAL", source="AUDIT",
            severity="ERROR", impact=7.0, effort=1.0, confidence=0.9, score=63.0,
            title="T", description="d", why="w", recommended_action="a")
        db.add(reco)
        db.commit()
        rep = seo.Report(organization_id=oid, project_id=pid, type="AUDIT")
        db.add(rep)
        db.commit()
        ids = {"org": org["id"], "proj": p["id"], "run": str(run.id),
               "issue": str(issue.id), "serp": str(s.id), "tracked": str(t.id),
               "keyword": str(kw.id), "comp": str(comp.id), "reco": str(reco.id),
               "report": str(rep.id)}
    finally:
        db.close()
    return ids


def test_cross_tenant_denied_everywhere():
    ids = _seed_owner_data()
    hb = _auth("tenant-b@example.com")
    o, p = ids["org"], ids["proj"]
    cases = [
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/overview", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/audits", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/audits/{ids['run']}", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/audits/{ids['run']}/issues", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/issues/{ids['issue']}/urls", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/serp", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/serp/{ids['serp']}", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/keywords", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/keywords/{ids['keyword']}", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/tracked-keywords", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/tracked-keywords/{ids['tracked']}/history", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/competitors", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/keyword-gap", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/gsc/overview", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/gsc/queries", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/gsc/pages", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/recommendations", None),
        ("GET", f"/api/v1/organizations/{o}/projects/{p}/reports", None),
        ("GET", f"/api/v1/organizations/{o}/limits", None),
        ("POST", f"/api/v1/organizations/{o}/projects/{p}/audits", {}),
        ("POST", f"/api/v1/organizations/{o}/projects/{p}/serp/search",
         {"keyword": "x"}),
        ("POST", f"/api/v1/organizations/{o}/projects/{p}/keywords/research",
         {"seed": "x"}),
        ("PATCH", f"/api/v1/recommendations/{ids['reco']}",
         {"status": "DISMISSED"}),
    ]
    for method, url, body in cases:
        if method == "GET":
            r = client.get(url, headers=hb)
        elif method == "POST":
            r = client.post(url, json=body, headers=hb)
        else:
            r = client.patch(url, json=body, headers=hb)
        assert r.status_code in (403, 404), f"{method} {url} → {r.status_code}"
