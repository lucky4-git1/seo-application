"""Shared rate limiter — one instance used by middleware + route decorators.

Limits are generous enough for normal UI polling but stop credential
stuffing and provider-cost abuse. Auth endpoints are tightest.
Set RATE_LIMIT_ENABLED=false to disable (tests do this; see
tests/conftest.py and tests/test_rate_limiting.py).
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower()
    not in ("0", "false", "no"),
)

AUTH_LIMIT = "20/minute"
EXPENSIVE_LIMIT = "30/minute"
