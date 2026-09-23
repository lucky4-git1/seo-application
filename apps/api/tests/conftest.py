"""Pytest bootstrap: env must be set before app modules import settings."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-xxxxxxxxxx")
# The shared limiter would otherwise 429 the suite (all TestClient calls
# share one IP). Rate limiting itself is covered by test_rate_limiting.py
# which re-enables the limiter explicitly.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
