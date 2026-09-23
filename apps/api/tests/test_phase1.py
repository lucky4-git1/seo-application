"""Backend tests: auth, tenant isolation, projects. Run with sqlite (no external services)."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, override_engine_for_tests  # noqa: E402
from app.main import app  # noqa: E402

engine = override_engine_for_tests("sqlite://")
Base.metadata.create_all(engine)
client = TestClient(app)


def register(email="a@example.com", password="password123"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def login(email="a@example.com", password="password123"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_login_me():
    register("u1@example.com")
    token = login("u1@example.com")
    r = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["email"] == "u1@example.com"


def test_duplicate_register_rejected():
    register("dup@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": "password123"})
    assert r.status_code == 400


def test_org_project_crud_and_tenant_isolation():
    register("owner@example.com")
    token = login("owner@example.com")
    h = auth_headers(token)

    r = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=h)
    assert r.status_code == 201, r.text
    org = r.json()

    r = client.post(f"/api/v1/organizations/{org['id']}/projects", json={"name": "Site", "domain": "https://www.Example.com/"}, headers=h)
    assert r.status_code == 201, r.text
    proj = r.json()
    assert proj["domain"] == "example.com"  # normalized

    # cross-tenant access denied: second user cannot see first org's project
    register("intruder@example.com")
    itoken = login("intruder@example.com")
    r = client.get(f"/api/v1/organizations/{org['id']}/projects", headers=auth_headers(itoken))
    assert r.status_code == 403

    # owner can patch + soft-delete
    r = client.patch(f"/api/v1/organizations/{org['id']}/projects/{proj['id']}", json={"name": "Site 2"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Site 2"
    r = client.delete(f"/api/v1/organizations/{org['id']}/projects/{proj['id']}", headers=h)
    assert r.status_code == 204
    r = client.get(f"/api/v1/organizations/{org['id']}/projects/{proj['id']}", headers=h)
    assert r.status_code == 404


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
