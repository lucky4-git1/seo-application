"""Steps 12–13 tests: competitor CRUD + gap computed from stored SERP data."""
from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

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


def _auth(email="gap@example.com"):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def _seed_serp(db, org_id, proj_id, keyword, rows):
    """rows: [(position, domain, url)] organic results in one stored search."""
    from app.serp import cache_key
    s = seo.SerpSearch(organization_id=org_id, project_id=proj_id, keyword=keyword,
                       cache_key=cache_key(keyword=keyword, engine="google",
                                           country="US", language="en",
                                           device="DESKTOP", location=None,
                                           provider="test", project_id=proj_id),
                       provider="test", searched_at=datetime.now(UTC))
    db.add(s)
    db.flush()
    for pos, domain, url in rows:
        db.add(seo.SerpResult(serp_search_id=s.id, position=pos, domain=domain,
                              url=url, result_type="organic"))
    db.commit()
    return s


def _seed_tracked(db, org_id, proj_id, keyword, rank):
    from app.keywords import normalize_keyword
    t = seo.TrackedKeyword(organization_id=org_id, project_id=proj_id,
                           keyword=keyword, normalized_keyword=normalize_keyword(keyword))
    db.add(t)
    db.commit()
    if rank is not None:
        db.add(seo.RankObservation(tracked_keyword_id=t.id,
                                   observed_at=datetime.now(UTC), rank=rank,
                                   ranking_url=f"https://gap-example.org/{keyword}"))
        db.commit()
    return t


def test_competitor_crud_validation():
    h = _auth()
    org = client.post("/api/v1/organizations", json={"name": "GOrg"}, headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "GP", "domain": "gap-example.org"}, headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"

    r = client.post(f"{base}/competitors", json={"domain": "https://Rival.com/x"},
                    headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["domain"] == "rival.com"
    comp_id = r.json()["id"]

    # duplicate reactivates, self-domain and garbage rejected
    assert client.post(f"{base}/competitors", json={"domain": "rival.com"},
                       headers=h).status_code == 201
    assert client.post(f"{base}/competitors", json={"domain": "gap-example.org"},
                       headers=h).status_code == 400
    assert client.post(f"{base}/competitors", json={"domain": "not a domain!!"},
                       headers=h).status_code in (400, 422)

    lst = client.get(f"{base}/competitors", headers=h).json()
    assert [c["domain"] for c in lst["items"]] == ["rival.com"]

    assert client.delete(f"{base}/competitors/{comp_id}", headers=h).status_code == 204
    assert client.get(f"{base}/competitors", headers=h).json()["items"] == []


def test_keyword_gap_buckets():
    h = _auth("gap2@example.com")
    org = client.post("/api/v1/organizations", json={"name": "GOrg2"}, headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "GP2", "domain": "gap2-example.org"}, headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"
    comp = client.post(f"{base}/competitors", json={"domain": "rival.com"},
                       headers=h).json()

    db = get_session_factory()()
    try:
        import uuid
        org_id = uuid.UUID(org["id"])
        proj_id = uuid.UUID(p["id"])
        _seed_tracked(db, org_id, proj_id, "alpha shoes", 18)   # weak (rival #3)
        _seed_tracked(db, org_id, proj_id, "beta shoes", None)  # missing
        _seed_tracked(db, org_id, proj_id, "gamma shoes", 2)    # strong
        _seed_serp(db, org_id, proj_id, "alpha shoes",
                   [(1, "other.com", "https://other.com/"),
                    (3, "rival.com", "https://rival.com/alpha"),
                    (18, "gap2-example.org", "https://gap2-example.org/alpha")])
        _seed_serp(db, org_id, proj_id, "beta shoes",
                   [(3, "rival.com", "https://rival.com/beta")])
        _seed_serp(db, org_id, proj_id, "gamma shoes",
                   [(2, "gap2-example.org", "https://gap2-example.org/gamma"),
                    (9, "rival.com", "https://rival.com/gamma")])
    finally:
        db.close()

    gap = client.get(f"{base}/keyword-gap", headers=h).json()
    by_kw = {r["keyword"]: r for r in gap["items"]}
    assert by_kw["alpha shoes"]["bucket"] == "weak"
    assert by_kw["alpha shoes"]["competitor_ranks"][comp["id"]] == 3
    assert by_kw["beta shoes"]["bucket"] == "missing"
    assert by_kw["beta shoes"]["your_rank"] is None
    assert by_kw["gamma shoes"]["bucket"] == "strong"

    only_missing = client.get(f"{base}/keyword-gap", params={"bucket": "missing"},
                              headers=h).json()
    assert [r["keyword"] for r in only_missing["items"]] == ["beta shoes"]

    ov = client.get(f"{base}/competitors/{comp['id']}/overview", headers=h).json()
    assert ov["serp_appearances"] == 3
    assert ov["avg_position"] == 5.0
    assert len(ov["top_pages"]) == 3

    csv = client.get(f"{base}/keyword-gap/export", headers=h)
    assert csv.status_code == 200
    assert "alpha shoes" in csv.text and csv.text.startswith("keyword,your_rank")
