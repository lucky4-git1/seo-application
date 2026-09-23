"""Step-2 tests: SEO schema — tables, constraints, cascades, tenant scoping.

Runs on SQLite via create_all (models must stay portable). The Postgres
migration 0002 is exercised separately with `alembic upgrade head`.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-min-32-chars-xxxxxxxxxx"

import app.models  # noqa: F401
import app.models_seo as seo
from app import models
from app.database import Base, override_engine_for_tests

engine = override_engine_for_tests("sqlite://")
Base.metadata.create_all(engine)
from app.database import get_session_factory

Session = get_session_factory()

EXPECTED_TABLES = {
    "domains", "competitors", "keywords", "keyword_metrics", "keyword_intents",
    "keyword_clusters", "tracked_keywords", "rank_observations", "serp_searches",
    "serp_results", "serp_features", "crawl_runs", "crawl_pages", "crawl_links",
    "audit_rules", "audit_issues", "audit_issue_instances", "gsc_connections",
    "gsc_properties", "gsc_query_data", "gsc_page_data", "recommendations",
    "reports", "report_exports", "provider_accounts", "provider_usage",
    "notifications", "users", "organizations", "organization_members",
    "projects", "jobs", "audit_logs",
}


def utcnow():
    return datetime.now(UTC)


def test_all_tables_registered():
    assert EXPECTED_TABLES <= set(Base.metadata.tables), (
        EXPECTED_TABLES - set(Base.metadata.tables))


@pytest.fixture
def org_project():
    db = Session()
    try:
        u = models.User(email=f"seo2-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
        db.add(u)
        db.flush()
        org = models.Organization(name="O2", slug=f"o2-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        db.add(models.OrganizationMember(organization_id=org.id, user_id=u.id, role="OWNER"))
        p = models.Project(organization_id=org.id, name="P2", domain="example.org",
                           competitors="[]")
        db.add(p)
        db.commit()
        yield db, org, p
    finally:
        db.close()


def test_competitor_unique_per_project(org_project):
    db, org, p = org_project
    db.add(seo.Competitor(organization_id=org.id, project_id=p.id,
                          domain="rival.com", original_input="https://rival.com/"))
    db.commit()
    db.add(seo.Competitor(organization_id=org.id, project_id=p.id,
                          domain="rival.com", original_input="rival.com"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_keyword_dedup_and_metrics(org_project):
    db, org, p = org_project
    kw = seo.Keyword(organization_id=org.id, project_id=p.id, keyword="Running Shoes",
                     normalized_keyword="running shoes", country="IN", language="en")
    db.add(kw)
    db.commit()
    db.add(seo.KeywordMetric(keyword_id=kw.id, search_volume=1000, provider="test"))
    db.add(seo.KeywordIntent(keyword_id=kw.id, intent="COMMERCIAL", confidence=0.8))
    db.commit()
    dup = seo.Keyword(organization_id=org.id, project_id=p.id, keyword="running shoes ",
                      normalized_keyword="running shoes", country="IN", language="en")
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_rank_tracking_chain(org_project):
    db, org, p = org_project
    t = seo.TrackedKeyword(organization_id=org.id, project_id=p.id,
                           keyword="shoes", normalized_keyword="shoes")
    db.add(t)
    db.commit()
    db.add(seo.RankObservation(tracked_keyword_id=t.id, observed_at=utcnow(), rank=7,
                               ranking_url="https://example.org/shoes"))
    db.add(seo.RankObservation(tracked_keyword_id=t.id, observed_at=utcnow(), rank=None))
    db.commit()
    assert db.query(seo.RankObservation).filter_by(tracked_keyword_id=t.id).count() == 2


def test_serp_search_cache_key_unique(org_project):
    db, org, p = org_project
    s = seo.SerpSearch(organization_id=org.id, project_id=p.id, keyword="shoes",
                       cache_key="k" * 32, provider="test", searched_at=utcnow())
    db.add(s)
    db.commit()
    db.add(seo.SerpResult(serp_search_id=s.id, position=1, domain="example.org",
                          url="https://example.org/"))
    db.commit()
    db.add(seo.SerpSearch(organization_id=org.id, keyword="shoes",
                          cache_key="k" * 32, provider="test", searched_at=utcnow()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_crawl_audit_recommendation_chain(org_project):
    db, org, p = org_project
    rule = seo.AuditRule(code="TITLE_MISSING", name="Missing title",
                         description="d", severity="ERROR", category="METADATA",
                         recommendation="r")
    db.add(rule)
    run = seo.CrawlRun(organization_id=org.id, project_id=p.id, status="COMPLETED")
    db.add(run)
    db.commit()
    page = seo.CrawlPage(crawl_run_id=run.id, url="https://example.org/",
                         normalized_url="https://example.org/", status_code=200)
    db.add(page)
    issue = seo.AuditIssue(
        organization_id=org.id, project_id=p.id, crawl_run_id=run.id,
        rule_id=rule.id, severity="ERROR", category="METADATA", message="m",
        why_it_matters="w", recommendation="r", affected_count=1,
        first_seen=utcnow(), last_seen=utcnow())
    db.add(issue)
    db.commit()
    db.add(seo.AuditIssueInstance(issue_id=issue.id, url="https://example.org/",
                                  detected_at=utcnow()))
    db.add(seo.Recommendation(
        organization_id=org.id, project_id=p.id, type="TECHNICAL",
        source="AUDIT", severity="ERROR", impact=8.0, effort=2.0,
        confidence=0.9, score=36.0, title="Add missing titles",
        description="d", why="w", recommended_action="a"))
    db.commit()
    assert db.query(seo.AuditIssue).filter_by(project_id=p.id).count() == 1
    assert db.query(seo.Recommendation).filter_by(project_id=p.id).count() == 1


def test_gsc_provider_report_models(org_project):
    db, org, p = org_project
    conn = seo.GscConnection(organization_id=org.id, access_token_enc="a",
                             refresh_token_enc="r")
    db.add(conn)
    db.commit()
    prop = seo.GscProperty(connection_id=conn.id, project_id=p.id,
                           site_url="https://example.org/")
    db.add(prop)
    db.commit()
    from datetime import date as d
    db.add(seo.GscQueryData(property_id=prop.id, date=d(2026, 9, 1), query="shoes",
                            clicks=10, impressions=100, ctr=0.1, position=7.5))
    db.add(seo.GscPageData(property_id=prop.id, date=d(2026, 9, 1),
                           page="https://example.org/shoes",
                           clicks=10, impressions=100, ctr=0.1, position=7.5))
    db.add(seo.ProviderAccount(organization_id=org.id, provider="dataforseo",
                               credentials_enc="enc"))
    db.add(seo.ProviderUsage(organization_id=org.id, provider="dataforseo",
                             service="serp", operation="search", units=3,
                             created_at=utcnow()))
    rep = seo.Report(organization_id=org.id, project_id=p.id, type="SEO_OVERVIEW")
    db.add(rep)
    db.commit()
    db.add(seo.ReportExport(report_id=rep.id, format="CSV"))
    db.add(seo.Notification(organization_id=org.id, type="AUDIT_DONE",
                            title="Audit complete", created_at=utcnow()))
    db.commit()


def test_project_cascade_wipes_tenant_data(org_project):
    db, org, p = org_project
    db.add(seo.Competitor(organization_id=org.id, project_id=p.id,
                          domain="gone.com", original_input="gone.com"))
    db.add(seo.Domain(organization_id=org.id, project_id=p.id,
                      original_input="https://example.org/", normalized_domain="example.org",
                      hostname="example.org"))
    db.commit()
    db.delete(p)
    db.commit()
    assert db.query(seo.Competitor).filter_by(project_id=p.id).count() == 0
    assert db.query(seo.Domain).filter_by(project_id=p.id).count() == 0
