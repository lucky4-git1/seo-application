"""Step-20: full MVP user journey end-to-end (API level, fakes for network).

Register → org → project → audit → keyword research → SERP → tracking →
competitor → gap → recommendations → report → download. Asserts each step's
output feeds the next — the workflow the product exists for.
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from datetime import UTC

from fastapi.testclient import TestClient

import app.models
import app.models_seo as seo
from app.celery_app import celery
from app.crawler.fetch import FetchResult
from app.database import (
    Base,
    get_engine,
    get_session_factory,
    override_engine_for_tests,
)
from app.main import app
from app.providers.base import KeywordMetrics, SerpResponse, SerpResultItem

celery.conf.task_always_eager = True
override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)

HOME = (b"<html><head><title>Journey Home Page Title Here Yes</title>"
        b'<meta name="description" content="A good description for the journey.">'
        b'<link rel="canonical" href="https://journey-example.org/">'
        b'</head><body><h1>Home</h1><p>' + b"word " * 400 + b"</p></body></html>")


def _fake_fetch(url: str, **kwargs) -> FetchResult:
    body = HOME if url == "https://journey-example.org/" else b""
    return FetchResult(url=url, requested_url=url,
                       status_code=200 if body else 404,
                       content_type="text/html" if body else "", body=body,
                       response_time_ms=40)


def _fake_discover(base_url: str, **kwargs) -> dict:
    return {"robots": {"disallows": [], "crawl_delay": None, "sitemaps": []},
            "seed_urls": [], "error": None}


class FakeSERP:
    name = "dataforseo"

    def __init__(self, *a, **k):
        pass

    def search(self, keyword, **kwargs):
        return SerpResponse(
            results=[SerpResultItem(position=4, domain="journey-example.org",
                                    url="https://journey-example.org/",
                                    title="Us", snippet="s"),
                     SerpResultItem(position=2, domain="rival.com",
                                    url="https://rival.com/", title="R")],
            features=[], provider_search_id="e2e")


class FakeKW:
    name = "dataforseo"

    def __init__(self, *a, **k):
        pass

    def metrics(self, keywords, **kwargs):
        return [KeywordMetrics(keyword=k, search_volume=8000, cpc=1.0,
                               competition=0.3, trend=[7000, 8000],
                               provider="dataforseo") for k in keywords]

    def suggestions(self, seed, **kwargs):
        return [KeywordMetrics(keyword=f"{seed} buy", search_volume=90000,
                               cpc=0.8, competition=0.25, trend=[80000, 90000],
                               provider="dataforseo"),
                KeywordMetrics(keyword=f"{seed} deals", search_volume=30000,
                               cpc=0.6, competition=0.15, trend=[25000, 30000],
                               provider="dataforseo")]


def _setup(monkeypatch):
    import app.crawler.discovery as disc
    import app.keyword_service as ks
    import app.serp as serp_service
    from app import tasks as taskmod
    from app.crawler import engine as crawl_engine
    from app.providers import dataforseo as dfs
    monkeypatch.setattr(crawl_engine, "fetch_url", _fake_fetch)
    monkeypatch.setattr(crawl_engine, "validate_url", lambda u: u)
    monkeypatch.setattr(disc, "discover_seeds", _fake_discover)
    monkeypatch.setattr(crawl_engine.discovery, "discover_seeds", _fake_discover)
    monkeypatch.setattr(serp_service, "DataForSEOSERP", FakeSERP)
    monkeypatch.setattr(ks, "DataForSEOKeywords", FakeKW)
    monkeypatch.setattr(dfs.DataForSEOSERP, "search",
                        lambda self, *a, **k: FakeSERP().search(*a, **k))
    monkeypatch.setattr(dfs.DataForSEOKeywords, "metrics",
                        lambda self, *a, **k: FakeKW().metrics(*a, **k))
    monkeypatch.setattr(dfs.DataForSEOKeywords, "suggestions",
                        lambda self, *a, **k: FakeKW().suggestions(*a, **k))

    def fake_send(name, args=None, kwargs=None, **kw):
        fn = {"seo.run_audit": taskmod.run_audit_task,
              "seo.fetch_serp": taskmod.fetch_serp_task,
              "seo.fetch_keywords": taskmod.fetch_keywords_task,
              "seo.track_rank": taskmod.track_rank_task,
              "seo.recalculate": taskmod.recalculate_task,
              "seo.generate_report": taskmod.generate_report_task}[name]
        return fn.apply(args=list(args or []), kwargs=dict(kwargs or {}))

    monkeypatch.setattr(celery, "send_task", fake_send)


def test_full_journey(monkeypatch):
    _setup(monkeypatch)
    # register → org → project
    assert client.post("/api/v1/auth/register",
                       json={"email": "journey@example.com",
                             "password": "password123"}).status_code == 201
    t = client.post("/api/v1/auth/login",
                    json={"email": "journey@example.com",
                          "password": "password123"}).json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    org = client.post("/api/v1/organizations", json={"name": "JOrg"},
                      headers=h).json()
    proj = client.post(f"/api/v1/organizations/{org['id']}/projects",
                       json={"name": "JP", "domain": "journey-example.org"},
                       headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{proj['id']}"
    client.post(f"/api/v1/organizations/{org['id']}/providers",
                json={"provider": "dataforseo",
                      "credentials": {"login": "l", "password": "p"}}, headers=h)

    # audit → health + issues
    run = client.post(f"{base}/audits", json={"max_pages": 5},
                      headers=h).json()["run"]
    det = client.get(f"{base}/audits/{run['id']}", headers=h).json()
    assert det["status"] == "COMPLETED" and det["pages_crawled"] == 1
    assert det["health_score"] is not None

    # keyword research → stored + scored
    assert client.post(f"{base}/keywords/research", json={"seed": "shoes"},
                       headers=h).status_code == 202
    kws = client.get(f"{base}/keywords", headers=h).json()
    assert kws["total"] == 2 and kws["items"][0]["opportunity"] is not None
    by_kw = {k["keyword"]: k for k in kws["items"]}
    assert by_kw["shoes buy"]["intent"] == "TRANSACTIONAL"

    # SERP → persisted results
    assert client.post(f"{base}/serp/search", json={"keyword": "shoes buy"},
                       headers=h).status_code == 202
    hist = client.get(f"{base}/serp", headers=h).json()
    assert hist["total"] == 1 and hist["items"][0]["results"] == 2

    # tracking → rank found for own domain (#4)
    tr = client.post(f"{base}/tracked-keywords", json={"keyword": "shoes buy"},
                     headers=h).json()
    assert tr["current_rank"] == 4

    # simulate an older better rank so the slip detector has signal
    import uuid
    from datetime import datetime, timedelta
    db = get_session_factory()()
    try:
        trow = db.query(seo.TrackedKeyword).filter_by(
            project_id=uuid.UUID(proj["id"]),
            normalized_keyword="shoes buy").first()
        db.add(seo.RankObservation(
            tracked_keyword_id=trow.id,
            observed_at=datetime.now(UTC) - timedelta(days=3),
            rank=1, ranking_url="https://journey-example.org/"))
        db.commit()
    finally:
        db.close()

    # competitor → gap shows weak (us #4 vs rival #2)
    comp = client.post(f"{base}/competitors", json={"domain": "rival.com"},
                       headers=h).json()
    gap = client.get(f"{base}/keyword-gap", headers=h).json()
    assert gap["total"] == 1
    assert gap["items"][0]["bucket"] == "weak"
    assert gap["items"][0]["competitor_ranks"][comp["id"]] == 2

    # recommendations → sources fire
    client.post(f"{base}/recommendations/recalculate", headers=h)
    recos = client.get(f"{base}/recommendations", headers=h).json()
    assert {"AUDIT", "KEYWORDS", "RANK_TRACKING", "GAP"} <= {
        i["source"] for i in recos["items"]}

    # overview aggregates the journey
    ov = client.get(f"{base}/overview", headers=h).json()
    assert ov["audit"]["health_score"] == det["health_score"]
    assert ov["tracked_keywords"] == 1 and ov["competitors"] == 1
    assert ov["open_recommendations"] == recos["total"]

    # report → CSV download
    rep = client.post(f"{base}/reports",
                      json={"type": "SEO_OVERVIEW", "format": "CSV"},
                      headers=h).json()
    lst = client.get(f"{base}/reports", headers=h).json()
    assert lst["items"][0]["status"] == "READY"
    dl = client.get(
        f"{base}/reports/exports/{rep['export']['id']}/download", headers=h)
    assert dl.status_code == 200
    assert dl.text.startswith("# Project") and "journey-example.org" in dl.text

    # limits reflect real usage
    lim = client.get(f"/api/v1/organizations/{org['id']}/limits",
                     headers=h).json()
    assert lim["usage"]["projects"] == 1
    assert lim["usage"]["monthly_serp"] >= 2  # serp search + rank check
