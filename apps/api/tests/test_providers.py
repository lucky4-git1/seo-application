"""Steps 6–8 unit tests: crypto, registry, intent/difficulty/opportunity,
DataForSEO normalization, SERP cache + rank finding. No network."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

import pytest

from app.keywords import (
    classify_intent,
    keyword_difficulty,
    normalize_keyword,
    opportunity_score,
)
from app.providers import crypto, registry
from app.providers.base import ProviderAuthError, ProviderError, ProviderQuotaError
from app.providers.dataforseo import (
    location_code_for,
    normalize_kw_item,
    normalize_serp_items,
)


def test_crypto_roundtrip_and_mask():
    blob = crypto.encrypt_credentials({"login": "me", "password": "supersecretpw"})
    assert "supersecretpw" not in blob
    assert crypto.decrypt_credentials(blob) == {"login": "me", "password": "supersecretpw"}
    masked = crypto.mask_credentials({"login": "me", "password": "supersecretpw"})
    assert masked["password"].startswith("su") and masked["password"].endswith("pw")
    assert "supersecretpw" not in masked["password"]
    with pytest.raises(ValueError):
        crypto.decrypt_credentials("garbage!!!")


def test_registry_validation():
    assert "login" in registry.required_fields("dataforseo")
    registry.validate_credentials("dataforseo", {"login": "a", "password": "b"})
    with pytest.raises(ValueError):
        registry.validate_credentials("dataforseo", {"login": "a"})
    with pytest.raises(KeyError):
        registry.required_fields("nope")


def test_error_codes():
    assert ProviderAuthError().code == "PROVIDER_AUTH"
    assert ProviderAuthError().retryable is False
    assert ProviderQuotaError().retryable is False


def test_normalize_keyword():
    assert normalize_keyword("  Running SHOES! ") == "running shoes"
    assert normalize_keyword("Café  crème") == "café crème"
    assert normalize_keyword("...") == ""


@pytest.mark.parametrize("kw,intent", [
    ("buy running shoes", "TRANSACTIONAL"),
    ("best running shoes 2026", "COMMERCIAL"),
    ("nike shoes vs adidas", "COMMERCIAL"),
    ("how to tie shoes", "INFORMATIONAL"),
    ("what is pronation", "INFORMATIONAL"),
    ("nike store near me", "LOCAL"),
    ("facebook login", "NAVIGATIONAL"),
])
def test_intent_heuristics(kw, intent):
    got, conf = classify_intent(kw)
    assert got == intent
    assert 0 < conf <= 1


def test_difficulty_and_opportunity():
    results = [{"domain": f"site{i}.com"} for i in range(10)]
    d, note = keyword_difficulty(serp_results=results, competition=0.8,
                                 search_volume=50000)
    assert 0 <= d <= 100 and "saturation" in note
    d2, _ = keyword_difficulty(serp_results=[], competition=0.1,
                               search_volume=50)
    assert d2 < d  # contested term scores higher
    opp = opportunity_score(search_volume=10000, difficulty=20.0,
                            intent="TRANSACTIONAL", current_rank=8)
    opp_hard = opportunity_score(search_volume=10000, difficulty=95.0,
                                 intent="TRANSACTIONAL", current_rank=8)
    assert opp > opp_hard > 0
    assert opportunity_score(search_volume=0, difficulty=0,
                             intent="INFORMATIONAL") == 0.0


def test_location_codes():
    assert location_code_for("US") == 2840
    assert location_code_for("in") == 2356
    assert location_code_for("XX", explicit=1234) == 1234
    with pytest.raises(ProviderError):
        location_code_for("XX")


SERP_ITEMS = [
    {"type": "organic", "rank_absolute": 1, "domain": "Example.COM",
     "url": "https://example.com/a", "title": "A", "description": "da"},
    {"type": "paid", "rank_absolute": 1, "domain": "ads.com",
     "url": "https://ads.com/", "title": "Ad", "description": "x"},
    {"type": "featured_snippet", "rank_absolute": 1,
     "items": [{"title": "FS", "url": "https://example.com/a"}]},
    {"type": "related_searches", "items": [{"title": "other"}]},
]


def test_normalize_serp_items():
    results, features = normalize_serp_items(SERP_ITEMS)
    assert len(results) == 2
    assert results[0].result_type == "organic" and results[0].position == 1
    assert results[0].domain == "example.com"  # lowercased host
    assert results[1].result_type == "paid"
    assert {f["feature_type"] for f in features} == {"featured_snippet",
                                                     "related_searches"}


def test_normalize_kw_item():
    m = normalize_kw_item({
        "keyword": "shoes", "search_volume": 12000, "cpc": 1.5,
        "competition_index": 73,
        "monthly_searches": [{"search_volume": i * 100} for i in range(14)]})
    assert m.keyword == "shoes"
    assert m.search_volume == 12000
    assert m.competition == pytest.approx(0.73)
    assert m.trend == [200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300]


def test_find_rank():
    import app.models_seo as seo
    from app.serp import find_rank
    rows = [seo.SerpResult(serp_search_id=None, position=1, domain="other.com",
                           url="https://other.com/", result_type="organic"),
            seo.SerpResult(serp_search_id=None, position=2, domain="www.example.com",
                           url="https://www.example.com/p", result_type="organic")]
    rank, url = find_rank(rows, "example.com")
    assert (rank, url) == (2, "https://www.example.com/p")
    assert find_rank(rows, "missing.com") == (None, None)
