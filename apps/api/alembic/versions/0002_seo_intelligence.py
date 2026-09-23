"""0002 SEO intelligence schema — domains, competitors, keywords, SERP, crawl,
audit, GSC, recommendations, reports, providers, notifications; harden jobs.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
NOW = sa.func.now()


def _ts(table: str) -> None:
    op.add_column(table, sa.Column("created_at", sa.DateTime(timezone=True),
                                   server_default=NOW, nullable=False))
    op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True),
                                   server_default=NOW, nullable=False))


def _org_fk(nullable=False):
    return sa.Column("organization_id", UUID,
                     sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                     nullable=nullable)


def _project_fk(nullable=False):
    return sa.Column("project_id", UUID,
                     sa.ForeignKey("projects.id", ondelete="CASCADE"),
                     nullable=nullable)


def upgrade() -> None:
    # -- jobs hardening -------------------------------------------------------
    op.add_column("jobs", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("result", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_org_status", "jobs", ["organization_id", "status"])
    op.create_index("ix_jobs_project", "jobs", ["project_id"])
    op.create_index("ix_jobs_type_status", "jobs", ["job_type", "status"])

    # -- domains --------------------------------------------------------------
    op.create_table(
        "domains",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("original_input", sa.String(253), nullable=False),
        sa.Column("normalized_domain", sa.String(253), nullable=False),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("protocol", sa.String(5), nullable=False, server_default="https"),
        sa.Column("www_variant", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", name="uq_domains_project"),
    )
    op.create_index("ix_domains_org", "domains", ["organization_id"])
    op.create_index("ix_domains_normalized", "domains", ["normalized_domain"])

    # -- competitors ----------------------------------------------------------
    op.create_table(
        "competitors",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("original_input", sa.String(253), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "domain", name="uq_competitor_project_domain"),
    )
    op.create_index("ix_competitors_org", "competitors", ["organization_id"])
    op.create_index("ix_competitors_project", "competitors", ["project_id"])
    _backfill_competitors()

    # -- keywords -------------------------------------------------------------
    op.create_table(
        "keyword_clusters",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="heuristic"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_keyword_clusters_project", "keyword_clusters", ["project_id"])

    op.create_table(
        "keywords",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(nullable=True),
        sa.Column("keyword", sa.String(500), nullable=False),
        sa.Column("normalized_keyword", sa.String(500), nullable=False),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("source", sa.String(40), nullable=False, server_default="provider"),
        sa.Column("cluster_id", UUID, sa.ForeignKey("keyword_clusters.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("organization_id", "normalized_keyword", "country", "language",
                            name="uq_keyword_org_norm_geo"),
    )
    op.create_index("ix_keywords_org", "keywords", ["organization_id"])
    op.create_index("ix_keywords_project", "keywords", ["project_id"])
    op.create_index("ix_keywords_normalized", "keywords", ["normalized_keyword"])

    op.create_table(
        "keyword_metrics",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("keyword_id", UUID, sa.ForeignKey("keywords.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("search_volume", sa.Integer, nullable=True),
        sa.Column("cpc", sa.Float, nullable=True),
        sa.Column("competition", sa.Float, nullable=True),
        sa.Column("trend", sa.JSON, nullable=True),
        sa.Column("intent", sa.String(20), nullable=True),
        sa.Column("difficulty", sa.Float, nullable=True),
        sa.Column("opportunity", sa.Float, nullable=True),
        sa.Column("serp_features", sa.JSON, nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_keyword_metrics_kw_time", "keyword_metrics",
                    ["keyword_id", "created_at"])

    op.create_table(
        "keyword_intents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("keyword_id", UUID, sa.ForeignKey("keywords.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("intent", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("method", sa.String(20), nullable=False, server_default="heuristic"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("keyword_id", "method", name="uq_intent_kw_method"),
    )
    op.create_index("ix_keyword_intents_kw", "keyword_intents", ["keyword_id"])
    op.create_index("ix_keyword_intents_intent", "keyword_intents", ["intent"])

    # -- rank tracking ---------------------------------------------------------
    op.create_table(
        "tracked_keywords",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("keyword_id", UUID, sa.ForeignKey("keywords.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("keyword", sa.String(500), nullable=False),
        sa.Column("normalized_keyword", sa.String(500), nullable=False),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("device", sa.String(10), nullable=False, server_default="DESKTOP"),
        sa.Column("engine", sa.String(20), nullable=False, server_default="google"),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "normalized_keyword", "country", "device",
                            "engine", name="uq_tracked_kw"),
    )
    op.create_index("ix_tracked_kw_org", "tracked_keywords", ["organization_id"])
    op.create_index("ix_tracked_kw_project", "tracked_keywords", ["project_id"])

    op.create_table(
        "rank_observations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tracked_keyword_id", UUID,
                  sa.ForeignKey("tracked_keywords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank", sa.Integer, nullable=True),
        sa.Column("ranking_url", sa.String(2000), nullable=True),
        sa.Column("serp_features", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_rank_obs_kw_time", "rank_observations",
                    ["tracked_keyword_id", "observed_at"])

    # -- SERP ------------------------------------------------------------------
    op.create_table(
        "serp_searches",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(nullable=True),
        sa.Column("keyword", sa.String(500), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False, server_default="google"),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("device", sa.String(10), nullable=False, server_default="DESKTOP"),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="COMPLETED"),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_search_id", sa.String(200), nullable=True),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("cache_key", name="uq_serp_cache_key"),
    )
    op.create_index("ix_serp_project_time", "serp_searches", ["project_id", "created_at"])

    op.create_table(
        "serp_results",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("serp_search_id", UUID,
                  sa.ForeignKey("serp_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=True),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.Column("result_type", sa.String(30), nullable=False, server_default="organic"),
        sa.Column("feature_type", sa.String(40), nullable=True),
        sa.UniqueConstraint("serp_search_id", "position", name="uq_serp_result_pos"),
    )
    op.create_index("ix_serp_result_domain", "serp_results", ["serp_search_id", "domain"])

    op.create_table(
        "serp_features",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("serp_search_id", UUID,
                  sa.ForeignKey("serp_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_type", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer, nullable=True),
        sa.Column("data", sa.JSON, nullable=True),
    )
    op.create_index("ix_serp_feature_search", "serp_features",
                    ["serp_search_id", "feature_type"])

    # -- crawler ---------------------------------------------------------------
    op.create_table(
        "crawl_runs",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_discovered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages_crawled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issues_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("health_score", sa.Float, nullable=True),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_crawl_runs_project_time", "crawl_runs", ["project_id", "created_at"])
    op.create_index("ix_crawl_runs_status", "crawl_runs", ["status"])

    op.create_table(
        "crawl_pages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("crawl_run_id", UUID, sa.ForeignKey("crawl_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("normalized_url", sa.String(2000), nullable=False),
        sa.Column("depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("response_time_ms", sa.Integer, nullable=True),
        sa.Column("title", sa.String(1000), nullable=True),
        sa.Column("title_length", sa.Integer, nullable=True),
        sa.Column("meta_description", sa.String(2000), nullable=True),
        sa.Column("meta_description_length", sa.Integer, nullable=True),
        sa.Column("canonical", sa.String(2000), nullable=True),
        sa.Column("robots_meta", sa.String(500), nullable=True),
        sa.Column("h1_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("h1_text", sa.JSON, nullable=True),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("images_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("images_missing_alt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("internal_links", sa.Integer, nullable=False, server_default="0"),
        sa.Column("external_links", sa.Integer, nullable=False, server_default="0"),
        sa.Column("redirect_target", sa.String(2000), nullable=True),
        sa.Column("indexability", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("is_noindex", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_nofollow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_robots_blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("schema_presence", sa.JSON, nullable=True),
        sa.Column("open_graph", sa.JSON, nullable=True),
        sa.Column("twitter_cards", sa.JSON, nullable=True),
        sa.Column("hreflang", sa.JSON, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("crawl_run_id", "normalized_url", name="uq_crawl_page_run_url"),
    )
    op.create_index("ix_crawl_pages_run", "crawl_pages", ["crawl_run_id"])
    op.create_index("ix_crawl_pages_status", "crawl_pages", ["crawl_run_id", "status_code"])
    op.create_index("ix_crawl_pages_hash", "crawl_pages", ["crawl_run_id", "content_hash"])

    op.create_table(
        "crawl_links",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("crawl_run_id", UUID, sa.ForeignKey("crawl_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("from_url", sa.String(2000), nullable=False),
        sa.Column("to_url", sa.String(2000), nullable=False),
        sa.Column("normalized_to_url", sa.String(2000), nullable=False),
        sa.Column("is_internal", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("rel", sa.String(200), nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
    )
    op.create_index("ix_crawl_links_run", "crawl_links", ["crawl_run_id"])
    op.create_index("ix_crawl_links_run_to", "crawl_links",
                    ["crawl_run_id", "normalized_to_url"])

    # -- audit -----------------------------------------------------------------
    op.create_table(
        "audit_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("code", name="uq_audit_rule_code"),
    )
    op.create_index("ix_audit_rules_category", "audit_rules", ["category", "enabled"])

    op.create_table(
        "audit_issues",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("crawl_run_id", UUID, sa.ForeignKey("crawl_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rule_id", UUID, sa.ForeignKey("audit_rules.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("why_it_matters", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("affected_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("crawl_run_id", "rule_id", name="uq_audit_issue_run_rule"),
    )
    op.create_index("ix_audit_issues_project_sev", "audit_issues", ["project_id", "severity"])
    op.create_index("ix_audit_issues_run", "audit_issues", ["crawl_run_id"])

    op.create_table(
        "audit_issue_instances",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("issue_id", UUID, sa.ForeignKey("audit_issues.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_instances_issue", "audit_issue_instances", ["issue_id"])

    # -- GSC -------------------------------------------------------------------
    op.create_table(
        "gsc_connections",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(),
        sa.Column("google_account", sa.String(320), nullable=True),
        sa.Column("access_token_enc", sa.Text, nullable=False),
        sa.Column("refresh_token_enc", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_gsc_conn_org", "gsc_connections", ["organization_id"])

    op.create_table(
        "gsc_properties",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connection_id", UUID,
                  sa.ForeignKey("gsc_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("site_url", sa.String(1000), nullable=False),
        sa.Column("property_type", sa.String(20), nullable=False, server_default="URL_PREFIX"),
        sa.Column("is_selected", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("connection_id", "site_url", name="uq_gsc_property"),
    )
    op.create_index("ix_gsc_prop_project", "gsc_properties", ["project_id"])

    for table, grain in (("gsc_query_data", "query"), ("gsc_page_data", "page")):
        op.create_table(
            table,
            sa.Column("id", UUID, primary_key=True),
            sa.Column("property_id", UUID,
                      sa.ForeignKey("gsc_properties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("date", sa.Date, nullable=False),
            sa.Column(grain, sa.String(2000 if grain == "page" else 1000), nullable=False),
            sa.Column("country", sa.String(3), nullable=False, server_default="all"),
            sa.Column("device", sa.String(10), nullable=False, server_default="all"),
            sa.Column("clicks", sa.Integer, nullable=False, server_default="0"),
            sa.Column("impressions", sa.Integer, nullable=False, server_default="0"),
            sa.Column("ctr", sa.Float, nullable=False, server_default="0"),
            sa.Column("position", sa.Float, nullable=False, server_default="0"),
            sa.UniqueConstraint("property_id", "date", grain, "country", "device",
                                name=f"uq_gsc_{grain}_grain"),
        )
        op.create_index(f"ix_gsc_{grain}_prop_date", table, ["property_id", "date"])

    # -- recommendations --------------------------------------------------------
    op.create_table(
        "recommendations",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("impact", sa.Float, nullable=False, server_default="0"),
        sa.Column("effort", sa.Float, nullable=False, server_default="1"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("why", sa.Text, nullable=False),
        sa.Column("recommended_action", sa.Text, nullable=False),
        sa.Column("related_url", sa.String(2000), nullable=True),
        sa.Column("related_keyword", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_reco_project_status", "recommendations", ["project_id", "status"])
    op.create_index("ix_reco_project_score", "recommendations", ["project_id", "score"])

    # -- reports -----------------------------------------------------------------
    op.create_table(
        "reports",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(), _project_fk(),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("params", sa.JSON, nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_reports_project_time", "reports", ["project_id", "created_at"])

    op.create_table(
        "report_exports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("report_id", UUID, sa.ForeignKey("reports.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_report_exports_report", "report_exports", ["report_id"])

    # -- providers ---------------------------------------------------------------
    op.create_table(
        "provider_accounts",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("label", sa.String(100), nullable=False, server_default="default"),
        sa.Column("credentials_enc", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="CONFIGURED"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("organization_id", "provider", "label",
                            name="uq_provider_account"),
    )
    op.create_index("ix_provider_accounts_org", "provider_accounts", ["organization_id"])

    op.create_table(
        "provider_usage",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("service", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(60), nullable=False),
        sa.Column("units", sa.Integer, nullable=False, server_default="1"),
        sa.Column("estimated_cost", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_provider_usage_org_time", "provider_usage",
                    ["organization_id", "created_at"])
    op.create_index("ix_provider_usage_provider", "provider_usage", ["provider"])

    # -- notifications ------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        _org_fk(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_notifications_org", "notifications", ["organization_id"])
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])


def _backfill_competitors() -> None:
    """Move projects.competitors JSON lists into the relational table."""
    from app.schemas import DOMAIN_RE, normalize_domain

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, organization_id, competitors FROM projects WHERE is_deleted = false"
    )).fetchall()
    for project_id, organization_id, raw in rows:
        try:
            entries = json.loads(raw or "[]")
        except (TypeError, ValueError):
            continue
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, str) or not entry.strip():
                continue
            domain = normalize_domain(entry)
            if not DOMAIN_RE.match(domain):
                continue
            if domain in seen:
                continue
            seen.add(domain)
            bind.execute(
                sa.text(
                    "INSERT INTO competitors (id, organization_id, project_id, domain,"
                    " original_input, is_active, created_at, updated_at)"
                    " VALUES (gen_random_uuid(), :org, :proj, :domain, :orig,"
                    " true, now(), now())"
                    " ON CONFLICT (project_id, domain) DO NOTHING"
                ),
                {"org": organization_id, "proj": project_id,
                 "domain": domain, "orig": entry.strip()},
            )


def downgrade() -> None:
    for table in ("notifications", "provider_usage", "provider_accounts",
                  "report_exports", "reports", "recommendations",
                  "gsc_page_data", "gsc_query_data", "gsc_properties",
                  "gsc_connections", "audit_issue_instances", "audit_issues",
                  "audit_rules", "crawl_links", "crawl_pages", "crawl_runs",
                  "serp_features", "serp_results", "serp_searches",
                  "rank_observations", "tracked_keywords", "keyword_intents",
                  "keyword_metrics", "keywords", "keyword_clusters",
                  "competitors", "domains"):
        op.drop_table(table)
    op.drop_index("ix_jobs_type_status", table_name="jobs")
    op.drop_index("ix_jobs_project", table_name="jobs")
    op.drop_index("ix_jobs_org_status", table_name="jobs")
    op.drop_column("jobs", "finished_at")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "result")
    op.drop_column("jobs", "payload")
