"""Step-11 tests: tracked keywords, rank observations, movements, history."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient

import app.models
import app.models_seo
from app.celery_app import celery
from app.database import Base, get_engine, override_engine_for_tests
from app.main import app
from app.providers.base import SerpResponse, SerpResultItem

celery.conf.task_always_eager = True
override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)


class RankedSERP:
    name = "dataforseo"

    def __init__(self, *a, **k):
        pass

    def search(self, keyword, **kwargs):
        return SerpResponse(
            results=[
                SerpResultItem(position=1, domain="other.com",
                               url="https://other.com/", title="O"),
                SerpResultItem(position=2, domain="rank-example.org",
                               url="https://rank-example.org/page",
                               title="Us", snippet="s"),
            ],
            features=[], provider_search_id="r1")


def _setup(monkeypatch):
    import app.serp as serp_service
    from app import tasks as taskmod
    monkeypatch.setattr(serp_service, "DataForSEOSERP", RankedSERP)

    def fake_send(name, args=None, kwargs=None, **kw):
        fn = {"seo.track_rank": taskmod.track_rank_task,
              "seo.track_scheduled_ranks": taskmod.track_scheduled_ranks}[name]
        return fn.apply(args=list(args or []), kwargs=dict(kwargs or {}))

    monkeypatch.setattr(celery, "send_task", fake_send)


def _auth(email="rank@example.com"):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def test_track_rank_flow(monkeypatch):
    _setup(monkeypatch)
    h = _auth()
    org = client.post("/api/v1/organizations", json={"name": "ROrg"}, headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "RP", "domain": "rank-example.org"}, headers=h).json()
    client.post(f"/api/v1/organizations/{org['id']}/providers",
                json={"provider": "dataforseo",
                      "credentials": {"login": "l", "password": "p"}}, headers=h)
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    # no provider state needed beyond account; first observation from eager task
    t = client.post(f"{base}/tracked-keywords", json={"keyword": "Shoes"}, headers=h)
    assert t.status_code == 201, t.text
    assert t.json()["current_rank"] == 2
    assert t.json()["current_url"] == "https://rank-example.org/page"

    # re-adding same keyword reactivates instead of duplicating
    client.delete(f"{base}/tracked-keywords/{t.json()['id']}", headers=h)
    r = client.post(f"{base}/tracked-keywords", json={"keyword": "shoes "}, headers=h)
    assert r.status_code == 201

    lst = client.get(f"{base}/tracked-keywords", headers=h).json()
    assert lst["total"] == 1
    row = lst["items"][0]
    assert row["best_rank"] == 2 and row["worst_rank"] == 2
    assert row["observations"] >= 1

    hist = client.get(f"{base}/tracked-keywords/{row['id']}/history", headers=h).json()
    assert len(hist["items"]) >= 1
    assert hist["items"][0]["rank"] == 2


def test_track_without_provider_fails_honestly(monkeypatch):
    _setup(monkeypatch)
    h = _auth("rank2@example.com")
    org = client.post("/api/v1/organizations", json={"name": "ROrg2"}, headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "RP2", "domain": "rank2-example.org"}, headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"
    t = client.post(f"{base}/tracked-keywords", json={"keyword": "Shoes"}, headers=h)
    assert t.status_code == 201
    assert t.json()["current_rank"] is None  # job failed honestly, nothing invented
    lst = client.get(f"{base}/tracked-keywords", headers=h).json()
    assert lst["items"][0]["observations"] == 0
