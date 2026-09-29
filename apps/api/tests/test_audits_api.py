"""Step-3/4 API tests: start audit → eager task crawls (mocked net) → issues.

Celery runs eager in-process; HTTP fetching and discovery are monkeypatched
so no test ever touches the network.
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient

import app.models
import app.models_seo
from app.celery_app import celery
from app.crawler import engine as crawl_engine
from app.crawler.fetch import FetchResult
from app.database import Base, get_engine, override_engine_for_tests
from app.main import app

celery.conf.task_always_eager = True

override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)

HOME = b"""<html><head><title>Home</title>
<meta name="description" content="Home page description here.">
<link rel="canonical" href="https://example.org/">
</head><body><h1>Home</h1><p>word </p>
<a href="https://example.org/about">about</a>
<a href="https://example.org/broken">broken</a>
<img src="/i.png" alt="x">
</body></html>"""
ABOUT = b"""<html><head></head><body><h1>About</h1><h1>Second</h1><p>about</p></body></html>"""


def _fake_fetch(url: str, **kwargs) -> FetchResult:
    bodies = {"https://example.org/": (HOME, 200),
              "https://example.org/about": (ABOUT, 200)}
    body, status = bodies.get(url, (b"", 404))
    return FetchResult(url=url, requested_url=url, status_code=status,
                       content_type="text/html" if body else "", body=body,
                       response_time_ms=50)


def _fake_discover(base_url: str, **kwargs) -> dict:
    return {"robots": {"disallows": [], "crawl_delay": None, "sitemaps": []},
            "seed_urls": [], "error": None}


def _setup(monkeypatch):
    monkeypatch.setattr(crawl_engine, "fetch_url", _fake_fetch)
    import app.crawler.discovery as disc
    monkeypatch.setattr(disc, "discover_seeds", _fake_discover)
    monkeypatch.setattr(crawl_engine.discovery, "discover_seeds", _fake_discover)
    # No broker in tests: execute the task inline instead of publishing.
    from app import celery_app
    from app.tasks import run_audit_task

    def fake_send(name, args=None, **kwargs):
        assert name == "seo.run_audit"
        return run_audit_task.apply(args=list(args or []))

    monkeypatch.setattr(celery_app.celery, "send_task", fake_send)


def _auth_headers():
    r = client.post("/api/v1/auth/register",
                    json={"email": "aud@example.com", "password": "password123"})
    assert r.status_code in (201, 400), r.text
    r = client.post("/api/v1/auth/login",
                    json={"email": "aud@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_audit_flow(monkeypatch):
    _setup(monkeypatch)
    h = _auth_headers()
    org = client.post("/api/v1/organizations", json={"name": "AuditCo"}, headers=h).json()
    proj = client.post(f"/api/v1/organizations/{org['id']}/projects",
                       json={"name": "S", "domain": "example.org"}, headers=h).json()

    r = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits",
        json={"max_pages": 10}, headers=h)
    assert r.status_code == 202, r.text
    run_id = r.json()["run"]["id"]
    assert r.json()["job"]["job_type"] == "RUN_AUDIT"

    # eager task already finished: run COMPLETED with real issues
    d = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits/{run_id}",
        headers=h).json()
    assert d["status"] == "COMPLETED", d
    assert d["pages_crawled"] == 3  # home + about + broken(404 stored)
    assert d["health_score"] is not None
    assert d["by_severity"]["ERROR"] >= 1

    issues = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits/{run_id}/issues",
        headers=h).json()
    codes = {i["rule_code"] for i in issues["items"]}
    assert "TITLE_MISSING" in codes  # about page has no title
    assert "BROKEN_PAGE" in codes
    assert "MULTIPLE_H1" in codes
    assert all("recommendation" in i and "why_it_matters" in i for i in issues["items"])

    filt = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits/{run_id}/issues",
        params={"severity": "ERROR"}, headers=h).json()
    assert all(i["severity"] == "ERROR" for i in filt["items"])

    first = issues["items"][0]
    urls = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/issues/{first['id']}/urls",
        headers=h).json()
    assert urls["total"] >= 1 and urls["items"][0]["url"].startswith("https://")

    listing = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits",
        headers=h).json()
    assert listing["total"] >= 1


def test_audit_tenant_isolation(monkeypatch):
    _setup(monkeypatch)
    h = _auth_headers()
    orgs = client.get("/api/v1/organizations", headers=h).json()
    org = orgs[0]
    r = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "Iso", "domain": "iso-example.org"}, headers=h)
    proj = r.json()

    # second user cannot start audits on first user's project
    client.post("/api/v1/auth/register",
                json={"email": "intruder2@example.com", "password": "password123"})
    t = client.post("/api/v1/auth/login",
                    json={"email": "intruder2@example.com", "password": "password123"}).json()
    ih = {"Authorization": f"Bearer {t['access_token']}"}
    r = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits",
        json={}, headers=ih)
    assert r.status_code == 403, r.text


def test_project_overview_aggregates(monkeypatch):
    _setup(monkeypatch)
    h = _auth_headers()
    org = client.post("/api/v1/organizations", json={"name": "OvOrg"}, headers=h).json()
    r = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "Ov", "domain": "example.org"}, headers=h)
    proj = r.json()

    ov = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/overview",
        headers=h).json()
    assert ov["project"]["domain"] == "example.org"
    assert ov["audit"] is None  # honest empty state, no fake numbers
    assert ov["tracked_keywords"] == 0
    assert ov["top_opportunities"] == []
    assert ov["gsc_connected"] is False

    r = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits",
        json={"max_pages": 5}, headers=h)
    assert r.status_code == 202
    ov = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/overview",
        headers=h).json()
    assert ov["audit"] is not None
    assert ov["audit"]["status"] == "COMPLETED"
    assert ov["audit"]["health_score"] is not None
    assert ov["latest_job"]["status"] == "COMPLETED"


def test_audit_pages_and_cancel_endpoints(monkeypatch):
    _setup(monkeypatch)
    h = _auth_headers()
    org = client.post("/api/v1/organizations", json={"name": "PagesOrg"}, headers=h).json()
    proj = client.post(f"/api/v1/organizations/{org['id']}/projects",
                       json={"name": "P", "domain": "example.org"}, headers=h).json()

    # Start audit
    r = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits",
        json={"max_pages": 10}, headers=h)
    assert r.status_code == 202
    run_id = r.json()["run"]["id"]

    # Test pages endpoint
    pages_res = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits/{run_id}/pages",
        headers=h)
    assert pages_res.status_code == 200
    pages_data = pages_res.json()
    assert "items" in pages_data
    assert len(pages_data["items"]) >= 1
    p = pages_data["items"][0]
    assert "url" in p
    assert "status_code" in p
    assert "indexability" in p

    # Test cancellation endpoint on completed audit
    cancel_res = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{proj['id']}/audits/{run_id}/cancel",
        headers=h)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["ok"] is True

