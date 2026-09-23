"""Rate limiting is real: hammering login past 20/min yields 429s."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

from fastapi.testclient import TestClient

import app.models
import app.models_seo
from app.database import Base, get_engine, override_engine_for_tests
from app.main import app
from app.ratelimit import limiter

override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())
client = TestClient(app)

BODY = {"email": "ratelimit@example.com", "password": "password123"}


def test_login_rate_limited(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    client.post("/api/v1/auth/register", json=BODY)
    statuses = set()
    for _ in range(25):
        r = client.post("/api/v1/auth/login", json=BODY)
        statuses.add(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, "expected login to be rate limited"
    assert r.json()["error"]["code"] == "RATE_LIMITED"
