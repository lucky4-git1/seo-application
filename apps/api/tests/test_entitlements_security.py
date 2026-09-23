"""Step 17/19 tests: entitlements, hardened validation, member rules."""
from __future__ import annotations

import os

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
from app.security import verify_password

override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)


def _auth(email):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code in (201, 400), r.text
    t = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def test_verify_password_fails_closed():
    assert verify_password("x", "not-a-valid-hash") is False
    assert verify_password("x", "") is False
    assert verify_password("x", "$argon2id$v=19$m=65536,t=3,p=4$short") is False


def test_project_limit_402():
    h = _auth("limits@example.com")
    org = client.post("/api/v1/organizations", json={"name": "LimOrg"},
                      headers=h).json()
    for i in range(3):
        r = client.post(f"/api/v1/organizations/{org['id']}/projects",
                        json={"name": f"P{i}", "domain": f"lim{i}-example.org"},
                        headers=h)
        assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "P3", "domain": "lim3-example.org"}, headers=h)
    assert r.status_code == 402
    assert "limit" in r.json()["detail"].lower()

    lim = client.get(f"/api/v1/organizations/{org['id']}/limits", headers=h).json()
    assert lim["plan"] == "FREE"
    assert lim["limits"]["projects"] == 3
    assert lim["usage"]["projects"] == 3


def test_audit_max_pages_clamped_to_plan(monkeypatch):
    from app.celery_app import celery

    def fake_send(*a, **k):
        class R:
            id = "x"
        return R()

    monkeypatch.setattr(celery, "send_task", fake_send)
    h = _auth("clamp@example.com")
    org = client.post("/api/v1/organizations", json={"name": "ClampOrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "CP", "domain": "clamp-example.org"},
                    headers=h).json()
    r = client.post(f"/api/v1/organizations/{org['id']}/projects/{p['id']}/audits",
                    json={"max_pages": 500}, headers=h)
    assert r.status_code == 202
    assert r.json()["run"]["max_pages_applied"] == 200  # FREE plan clamp


def test_tracked_limit_402(monkeypatch):
    from app.celery_app import celery
    monkeypatch.setattr(celery, "send_task", lambda *a, **k: None)
    h = _auth("tlim@example.com")
    org = client.post("/api/v1/organizations", json={"name": "TLOrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "TLP", "domain": "tlim-example.org"},
                    headers=h).json()
    import uuid
    db = get_session_factory()()
    try:
        for i in range(25):
            db.add(seo.TrackedKeyword(
                organization_id=uuid.UUID(org["id"]),
                project_id=uuid.UUID(p["id"]), keyword=f"kw{i}",
                normalized_keyword=f"kw{i}"))
        db.commit()
    finally:
        db.close()
    r = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{p['id']}/tracked-keywords",
        json={"keyword": "one more"}, headers=h)
    assert r.status_code == 402


def test_member_rules():
    owner_h = _auth("owner3@example.com")
    org = client.post("/api/v1/organizations", json={"name": "MemOrg"},
                      headers=owner_h).json()
    # unknown org → 404, not 500
    r = client.post("/api/v1/organizations/00000000-0000-0000-0000-000000000000/members",
                    json={"email": "x@y.z", "role": "MEMBER"}, headers=owner_h)
    assert r.status_code == 404

    client.post("/api/v1/auth/register",
                json={"email": "admin3@example.com", "password": "password123"})
    t = client.post("/api/v1/auth/login",
                    json={"email": "admin3@example.com", "password": "password123"}).json()
    admin_h = {"Authorization": f"Bearer {t['access_token']}"}
    r = client.post(f"/api/v1/organizations/{org['id']}/members",
                    json={"email": "admin3@example.com", "role": "ADMIN"},
                    headers=owner_h)
    assert r.status_code == 201
    # ADMIN cannot grant OWNER
    r = client.post(f"/api/v1/organizations/{org['id']}/members",
                    json={"email": "admin3@example.com", "role": "OWNER"},
                    headers=admin_h)
    assert r.status_code == 403


def test_project_update_validation():
    h = _auth("upd@example.com")
    org = client.post("/api/v1/organizations", json={"name": "UpdOrg"},
                      headers=h).json()
    p = client.post(f"/api/v1/organizations/{org['id']}/projects",
                    json={"name": "UP", "domain": "upd-example.org"},
                    headers=h).json()
    base = f"/api/v1/organizations/{org['id']}/projects/{p['id']}"
    assert client.patch(base, json={"country": "USA"}, headers=h).status_code == 422
    assert client.patch(base, json={"device": "TV"}, headers=h).status_code == 422
    assert client.patch(base, json={"competitors": ["not a domain!!"]},
                        headers=h).status_code == 422
    r = client.patch(base, json={"competitors": ["https://Rival.com/x", "rival.com"]},
                     headers=h)
    assert r.status_code == 200
    assert r.json()["competitors"] == ["rival.com"]  # normalized + deduped
    r = client.patch(base, json={"competitors": ["upd-example.org"]}, headers=h)
    assert r.status_code == 400  # self-competitor rejected
