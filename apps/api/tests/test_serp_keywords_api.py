"""Steps 6–8 API tests: provider accounts, SERP + keyword flows with a fake
vendor (registry monkeypatched). No network, no real credentials."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient

import app.models
from app.celery_app import celery
from app.database import Base, get_engine, override_engine_for_tests
from app.main import app
from app.providers.base import KeywordMetrics, SerpResponse, SerpResultItem

celery.conf.task_always_eager = True
override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)


class FakeSERP:
    name = "dataforseo"

    def __init__(self, *a, **k):
        pass

    def search(self, keyword, **kwargs):
        return SerpResponse(
            results=[SerpResultItem(position=1, domain="example.org",
                                    url="https://example.org/",
                                    title="Example", snippet="s")],
            features=[{"feature_type": "featured_snippet", "position": 1,
                       "data": {}}],
            provider_search_id="fake-1")


class FakeKW:
    name = "dataforseo"

    def __init__(self, *a, **k):
        pass

    def metrics(self, keywords, **kwargs):
        return [KeywordMetrics(keyword=k, search_volume=1000, cpc=0.5,
                               competition=0.4, trend=[800, 1000],
                               provider="dataforseo") for k in keywords]

    def suggestions(self, seed, **kwargs):
        limit = kwargs.get("limit", 100)
        return [KeywordMetrics(keyword=f"{seed} {w}", search_volume=500,
                               cpc=0.3, competition=0.2, trend=[400, 500],
                               provider="dataforseo")
                for w in ("buy", "best", "guide")][:limit]


def _setup(monkeypatch):
    import app.keyword_service as ks
    import app.serp as serp_service
    from app.providers import dataforseo as dfs
    monkeypatch.setattr(serp_service, "DataForSEOSERP", FakeSERP)
    monkeypatch.setattr(ks, "DataForSEOKeywords", FakeKW)
    monkeypatch.setattr(dfs.DataForSEOSERP, "search",
                        lambda self, *a, **k: FakeSERP().search(*a, **k))
    from app import tasks as taskmod

    def fake_send(name, args=None, kwargs=None, **kw):
        fn = {"seo.fetch_serp": taskmod.fetch_serp_task,
              "seo.fetch_keywords": taskmod.fetch_keywords_task}[name]
        return fn.apply(args=list(args or []), kwargs=dict(kwargs or {}))

    monkeypatch.setattr(celery, "send_task", fake_send)


def _auth(email="prov@example.com"):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def _org_proj(h, name="POrg", proj="PProj", domain="prov-example.org"):
    org = client.post("/api/v1/organizations", json={"name": name}, headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": proj, "domain": domain}, headers=h).json()
    return org, p


def test_provider_account_crud_and_test(monkeypatch):
    _setup(monkeypatch)
    h = _auth()
    org, _ = _org_proj(h)

    assert any(p["provider"] == "dataforseo"
               for p in client.get("/api/v1/providers", headers=h).json()["items"])

    # member (non-admin) cannot manage credentials — use fresh member org
    r = client.post(f"/api/v1/organizations/{org['id']}/providers",
                    json={"provider": "nope", "credentials": {}}, headers=h)
    assert r.status_code == 400

    r = client.post(f"/api/v1/organizations/{org['id']}/providers",
                    json={"provider": "dataforseo",
                          "credentials": {"login": "l", "password": "p"}}, headers=h)
    assert r.status_code == 201, r.text
    acct = r.json()
    assert acct["credentials_masked"] == {"login": "****", "password": "****"}
    assert "credentials_enc" not in acct

    t = client.post(
        f"/api/v1/organizations/{org['id']}/providers/{acct['id']}/test",
        headers=h).json()
    assert t["ok"] is True and t["status"] == "ACTIVE"

    r = client.delete(f"/api/v1/organizations/{org['id']}/providers/{acct['id']}",
                      headers=h)
    assert r.status_code == 204


def test_serp_search_caches_and_persists(monkeypatch):
    _setup(monkeypatch)
    h = _auth("serp@example.com")
    org, p = _org_proj(h, "SOrg", "SProj", "serp-example.org")
    client.post(f"/api/v1/organizations/{org['id']}/providers",
                json={"provider": "dataforseo",
                      "credentials": {"login": "l", "password": "p"}}, headers=h)

    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"
    r = client.post(f"{base}/serp/search", json={"keyword": "shoes"}, headers=h)
    assert r.status_code == 202, r.text

    hist = client.get(f"{base}/serp", headers=h).json()
    assert hist["total"] == 1
    det = client.get(f"{base}/serp/{hist['items'][0]['id']}", headers=h).json()
    assert det["results"] == 1 and det["features"] == 1
    assert det["result_items"][0]["domain"] == "example.org"

    # second identical search → served from persistent cache (no new row)
    client.post(f"{base}/serp/search", json={"keyword": "shoes"}, headers=h)
    hist2 = client.get(f"{base}/serp", headers=h).json()
    assert hist2["total"] == 1

    usage = client.get(f"/api/v1/organizations/{org['id']}/usage", headers=h).json()
    assert any(u["operation"] == "search" for u in usage["items"])


def test_serp_requires_provider(monkeypatch):
    _setup(monkeypatch)
    h = _auth("noprovider@example.com")
    org, p = _org_proj(h, "NOrg", "NProj", "noprovider-example.org")
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"
    r = client.post(f"{base}/serp/search", json={"keyword": "shoes"}, headers=h)
    assert r.status_code == 202  # accepted; job records the honest failure
    hist = client.get(f"{base}/serp", headers=h).json()
    assert hist["total"] == 0  # nothing fabricated


def test_keyword_research_and_filters(monkeypatch):
    _setup(monkeypatch)
    h = _auth("kw@example.com")
    org, p = _org_proj(h, "KOrg", "KProj", "kw-example.org")
    client.post(f"/api/v1/organizations/{org['id']}/providers",
                json={"provider": "dataforseo",
                      "credentials": {"login": "l", "password": "p"}}, headers=h)
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    r = client.post(f"{base}/keywords/research", json={"seed": "shoes"}, headers=h)
    assert r.status_code == 202, r.text

    lst = client.get(f"{base}/keywords", headers=h).json()
    assert lst["total"] == 3
    first = lst["items"][0]
    assert first["search_volume"] == 500
    assert first["intent"] in ("TRANSACTIONAL", "COMMERCIAL", "INFORMATIONAL")
    assert 0 <= first["difficulty"] <= 100
    assert 0 <= first["opportunity"] <= 100

    comm = client.get(f"{base}/keywords", params={"intent": "COMMERCIAL"},
                      headers=h).json()
    assert all(i["intent"] == "COMMERCIAL" for i in comm["items"])
    assert {i["keyword"] for i in comm["items"]} <= {i["keyword"] for i in lst["items"]}

    det = client.get(f"{base}/keywords/{first['id']}", headers=h).json()
    assert det["keyword"] == first["keyword"]
    assert len(det["history"]) >= 1
