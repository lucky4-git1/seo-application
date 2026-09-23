"""Step-14 tests: GSC OAuth scaffolding, sync (mocked Google), reads."""
from __future__ import annotations

import os

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
from app.providers import crypto

celery.conf.task_always_eager = True
override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)

QUERY_ROWS = [
    {"keys": ["2026-09-20", "shoes", "usa", "DESKTOP"], "clicks": 10,
     "impressions": 1000, "ctr": 0.01, "position": 8.0},
    {"keys": ["2026-09-21", "shoes", "usa", "DESKTOP"], "clicks": 12,
     "impressions": 1100, "ctr": 0.0109, "position": 7.5},
]
PAGE_ROWS = [
    {"keys": ["2026-09-20", "https://gsc-example.org/", "usa", "DESKTOP"],
     "clicks": 20, "impressions": 2000, "ctr": 0.01, "position": 6.0},
]


class FakeSC:
    def __init__(self, *a, **k):
        pass

    def list_properties(self):
        return [{"site_url": "https://gsc-example.org/",
                 "property_type": "URL_PREFIX"}]

    def query_analytics(self, site_url, start, end, dimensions, **kwargs):
        if "query" in dimensions:
            return QUERY_ROWS
        return PAGE_ROWS


def _setup(monkeypatch):
    import app.gsc as gsc_service
    from app import tasks as taskmod
    monkeypatch.setattr(gsc_service, "SearchConsoleClient", FakeSC)

    def fake_send(name, args=None, kwargs=None, **kw):
        assert name == "seo.sync_gsc"
        return taskmod.sync_gsc_task.apply(args=list(args or []),
                                           kwargs=dict(kwargs or {}))

    monkeypatch.setattr(celery, "send_task", fake_send)


def _auth(email="gsc@example.com"):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def _make_conn(db, org_id):
    conn = seo.GscConnection(
        organization_id=org_id,
        google_account="tester@gmail.com",
        access_token_enc=crypto.encrypt_credentials({"token": "at"}),
        refresh_token_enc=crypto.encrypt_credentials({"token": "rt"}))
    db.add(conn)
    db.commit()
    prop = seo.GscProperty(connection_id=conn.id,
                           site_url="https://gsc-example.org/")
    db.add(prop)
    db.commit()
    return conn, prop


def test_auth_url_requires_google_config():
    h = _auth()
    org = client.post("/api/v1/organizations", json={"name": "GscOrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "GP", "domain": "gsc-example.org"},
                    headers=h).json()
    r = client.get(f"/api/v1/organizations/{org['id']}/projects/{p['id']}/gsc/auth-url",
                   headers=h)
    # no GOOGLE_CLIENT_ID in test env → honest 503, not a fake URL
    assert r.status_code == 503
    assert "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_sync_flow_and_reads(monkeypatch):
    _setup(monkeypatch)
    h = _auth("gsc2@example.com")
    org = client.post("/api/v1/organizations", json={"name": "GscOrg2"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "GP2", "domain": "gsc-example.org"},
                    headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    import uuid
    db = get_session_factory()()
    try:
        _conn, prop = _make_conn(db, uuid.UUID(org["id"]))
        prop_id = str(prop.id)
    finally:
        db.close()

    # select via correct endpoint body
    r = client.post(f"{base}/gsc/select", json={"property_id": prop_id}, headers=h)
    assert r.status_code == 200, r.text

    r = client.post(f"{base}/gsc/sync", json={"days": 30}, headers=h)
    assert r.status_code == 202, r.text

    ov = client.get(f"{base}/gsc/overview", headers=h).json()
    assert ov["queries"]["clicks"] == 22
    assert ov["queries"]["impressions"] == 2100
    assert ov["pages"]["clicks"] == 20
    assert len(ov["daily"]) == 2

    qs = client.get(f"{base}/gsc/queries", headers=h).json()
    assert qs["total"] == 1 and qs["items"][0]["query"] == "shoes"
    assert qs["items"][0]["position"] == 7.8  # avg of 8.0, 7.5 → 7.75 → 7.8

    pgs = client.get(f"{base}/gsc/pages", headers=h).json()
    assert pgs["total"] == 1

    # re-sync is idempotent (updates, no duplicates)
    client.post(f"{base}/gsc/sync", json={"days": 30}, headers=h)
    qs2 = client.get(f"{base}/gsc/queries", headers=h).json()
    assert qs2["total"] == 1

    conns = client.get(f"{base}/gsc/connections", headers=h).json()
    assert conns["items"][0]["properties"][0]["is_selected"] is True
    blob = str(conns["items"])
    assert "access_token_enc" not in blob and "refresh_token_enc" not in blob
