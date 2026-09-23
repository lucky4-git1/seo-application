"""Provider interfaces — business logic depends on these, never on vendors.

A provider call takes plain dicts and returns plain dicts (JSON-safe), so
services stay decoupled from httpx/vendor SDKs and tests can fake providers
without network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SerpResultItem:
    position: int
    domain: str
    url: str
    title: str | None = None
    snippet: str | None = None
    result_type: str = "organic"  # organic|paid|...
    feature_type: str | None = None


@dataclass
class SerpResponse:
    results: list[SerpResultItem] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)  # {feature_type, position?, data}
    provider_search_id: str | None = None
    raw: dict | None = None


@dataclass
class KeywordMetrics:
    keyword: str
    search_volume: int | None = None
    cpc: float | None = None
    competition: float | None = None  # 0..1
    trend: list | None = None  # monthly volumes, oldest → newest
    provider: str = ""


class ProviderError(Exception):
    """Base for all provider failures (auth, quota, network, bad response)."""

    def __init__(self, message: str, *, code: str = "PROVIDER_ERROR",
                 retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProviderAuthError(ProviderError):
    def __init__(self, message: str = "Provider authentication failed"):
        super().__init__(message, code="PROVIDER_AUTH", retryable=False)


class ProviderQuotaError(ProviderError):
    def __init__(self, message: str = "Provider quota exceeded"):
        super().__init__(message, code="PROVIDER_QUOTA", retryable=False)


class SERPProvider(Protocol):
    name: str

    def search(self, keyword: str, *, country: str, language: str,
               device: str, location: str | None = None,
               location_code: int | None = None,
               depth: int = 20) -> SerpResponse:
        """Run a live SERP query. Raises ProviderError on failure."""
        ...


class KeywordProvider(Protocol):
    name: str

    def metrics(self, keywords: list[str], *, country: str,
                language: str) -> list[KeywordMetrics]:
        """Provider metrics for explicit keywords (no invention)."""
        ...

    def suggestions(self, seed: str, *, country: str, language: str,
                    limit: int = 100) -> list[KeywordMetrics]:
        """Related keyword ideas + metrics for a seed keyword."""
        ...
