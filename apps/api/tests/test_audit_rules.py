"""Step-4 tests: audit rules on synthetic pages + health-score math."""
from __future__ import annotations

import os
from collections import Counter

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

import app.models
import app.models_seo  # noqa: F401
from app.audit import engine as audit_engine
from app.audit.rules import (
    BUCKET_WEIGHTS,
    Ctx,
    health_score,
    rule_index,
    score_bucket,
)
from app.database import (
    Base,
    get_engine,
    get_session_factory,
    override_engine_for_tests,
)
from app.models_seo import AuditRule

override_engine_for_tests("sqlite://")
Base.metadata.create_all(get_engine())


def _page(url, **kw):
    d = {"url": url, "normalized_url": url, "depth": 1, "status_code": 200,
         "response_time_ms": 100, "title": "A Decent Title With Enough Length Here",
         "meta_description": "A perfectly fine meta description of good length here.",
         "canonical": url, "canonical_normalized": url, "h1_count": 1,
         "word_count": 500, "images_missing_alt": 0, "is_noindex": False,
         "is_robots_blocked": False, "schema_presence": ["Article"],
         "hreflang": {}, "content_hash": f"h-{url}", "out_links": [],
         "redirect_target_normalized": ""}
    d.update(kw)
    return d


def _ctx(pages):
    by_url = {p["normalized_url"]: p for p in pages}
    ok = {p["normalized_url"] for p in pages if p["status_code"] == 200}
    return Ctx(pages=pages, inbound=Counter(), by_url=by_url, ok_urls=ok,
               run={"pages_crawled": len(pages)})


def test_title_and_meta_rules():
    idx = rule_index()
    home = _page("https://a.com/")
    bad = _page("https://a.com/bad", title=None, meta_description=None, h1_count=0,
                word_count=50, images_missing_alt=2, schema_presence=[])
    ctx = _ctx([home, bad])
    assert idx["TITLE_MISSING"].check(ctx) == ["https://a.com/bad"]
    assert idx["META_DESCRIPTION_MISSING"].check(ctx) == ["https://a.com/bad"]
    assert idx["H1_MISSING"].check(ctx) == ["https://a.com/bad"]
    assert idx["THIN_CONTENT"].check(ctx) == ["https://a.com/bad"]
    assert idx["MISSING_IMAGE_ALT"].check(ctx) == ["https://a.com/bad"]
    assert idx["MISSING_STRUCTURED_DATA"].check(ctx) == ["https://a.com/bad"]
    assert idx["TITLE_MISSING"].check(ctx) != ["https://a.com/"]


def test_duplicates_and_broken_and_redirects():
    idx = rule_index()
    p1 = _page("https://a.com/1", title="Same Title Here Yes Indeed",
               meta_description="Same description here yes indeed ok",
               content_hash="abc")
    p2 = _page("https://a.com/2", title="Same Title Here Yes Indeed",
               meta_description="Same description here yes indeed ok",
               content_hash="abc")
    gone = _page("https://a.com/gone", status_code=404)
    p1["out_links"] = [{"normalized_to_url": "https://a.com/gone"}]
    r1 = _page("https://a.com/r1", status_code=301,
               redirect_target_normalized="https://a.com/r2")
    r2 = _page("https://a.com/r2", status_code=301,
               redirect_target_normalized="https://a.com/r1")
    ctx = _ctx([p1, p2, gone, r1, r2])
    assert set(idx["DUPLICATE_TITLE"].check(ctx)) == {"https://a.com/1", "https://a.com/2"}
    assert set(idx["DUPLICATE_CONTENT"].check(ctx)) == {"https://a.com/1", "https://a.com/2"}
    assert idx["BROKEN_PAGE"].check(ctx) == ["https://a.com/gone"]
    assert idx["BROKEN_INTERNAL_LINK"].check(ctx) == ["https://a.com/1"]
    assert set(idx["REDIRECT_LOOP"].check(ctx)) == {"https://a.com/r1", "https://a.com/r2"}


def test_noindex_canonical_https_slow():
    idx = rule_index()
    pages = [
        _page("https://a.com/n", is_noindex=True),
        _page("https://a.com/c", canonical="https://a.com/other",
              canonical_normalized="https://a.com/other"),
        _page("http://a.com/plain"),
        _page("https://a.com/slow", response_time_ms=5000),
    ]
    ctx = _ctx(pages)
    assert idx["NOINDEX_PAGE"].check(ctx) == ["https://a.com/n"]
    assert idx["CANONICAL_CONFLICT"].check(ctx) == ["https://a.com/c"]
    assert idx["HTTP_PAGE"].check(ctx) == ["http://a.com/plain"]
    assert idx["SLOW_PAGE"].check(ctx) == ["https://a.com/slow"]


def test_score_math():
    assert score_bucket([], 10) == 100.0
    # 1 ERROR on 1 of 10 pages: 100 - 25*0.1 = 97.5
    assert score_bucket([{"severity": "ERROR", "affected_count": 1}], 10) == 97.5
    # 2 CRITICALs everywhere: 100 - 2*60 floors at 0
    assert score_bucket([{"severity": "CRITICAL", "affected_count": 5},
                         {"severity": "CRITICAL", "affected_count": 5}], 5) == 0.0
    full = {b: 100.0 for b in BUCKET_WEIGHTS}
    assert health_score(full) == 100.0
    assert health_score({b: 0.0 for b in BUCKET_WEIGHTS}) == 0.0
    mixed = {b: 50.0 for b in BUCKET_WEIGHTS}
    assert health_score(mixed) == 50.0


def test_seed_rules_idempotent():
    db = get_session_factory()()
    try:
        n1 = audit_engine.seed_rules(db)
        n2 = audit_engine.seed_rules(db)
        assert n1 == n2 > 20
        assert db.query(AuditRule).count() == n1
    finally:
        db.close()
