"""SEO intelligence domain models (Step 2 of transformation).

All tenant-owned tables carry organization_id (+ project_id where scoped).
Conventions: UUID PKs, FKs with CASCADE, explicit indexes for hot query paths,
unique constraints for idempotency/dedup, JSON only for genuinely flexible
payloads (trends, serp features, hreflang maps, report params).

Types are kept portable (no Postgres-only column types) so unit tests can run
on SQLite via Base.metadata.create_all; the Alembic migration targets PG.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import TimestampMixin, _uuid


# ---------------------------------------------------------------- domains ---
class Domain(Base, TimestampMixin):
    """Canonical domain record for a project (rich version of Project.domain)."""

    __tablename__ = "domains"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    original_input: Mapped[str] = mapped_column(String(253), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    protocol: Mapped[str] = mapped_column(String(5), default="https", nullable=False)
    www_variant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ------------------------------------------------------------ competitors ---
class Competitor(Base, TimestampMixin):
    """Relational competitor (replaces projects.competitors JSON)."""

    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_competitor_project_domain"),
        Index("ix_competitors_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    original_input: Mapped[str] = mapped_column(String(253), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --------------------------------------------------------------- keywords ---
class Keyword(Base, TimestampMixin):
    """Deduplicated keyword identity per org/country/language."""

    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_keyword", "country", "language",
                         name="uq_keyword_org_norm_geo"),
        Index("ix_keywords_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="provider", nullable=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("keyword_clusters.id", ondelete="SET NULL"), nullable=True, index=True)

    metrics: Mapped[list[KeywordMetric]] = relationship(
        back_populates="keyword", cascade="all,delete-orphan")
    intents: Mapped[list[KeywordIntent]] = relationship(
        back_populates="keyword", cascade="all,delete-orphan")


class KeywordMetric(Base, TimestampMixin):
    """Point-in-time provider metrics for a keyword. Source always recorded."""

    __tablename__ = "keyword_metrics"
    __table_args__ = (Index("ix_keyword_metrics_kw_time", "keyword_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    keyword_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False)
    search_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpc: Mapped[float | None] = mapped_column(Float, nullable=True)
    competition: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[list | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    opportunity: Mapped[float | None] = mapped_column(Float, nullable=True)
    serp_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)

    keyword: Mapped[Keyword] = relationship(back_populates="metrics")


class KeywordIntent(Base, TimestampMixin):
    """Intent classification record (heuristic or AI) with confidence."""

    __tablename__ = "keyword_intents"
    __table_args__ = (
        UniqueConstraint("keyword_id", "method", name="uq_intent_kw_method"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    keyword_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False, index=True)
    intent: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="heuristic", nullable=False)

    keyword: Mapped[Keyword] = relationship(back_populates="intents")


class KeywordCluster(Base, TimestampMixin):
    __tablename__ = "keyword_clusters"
    __table_args__ = (Index("ix_keyword_clusters_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="heuristic", nullable=False)


# ---------------------------------------------------------- rank tracking ---
class TrackedKeyword(Base, TimestampMixin):
    __tablename__ = "tracked_keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_keyword", "country", "device",
                         "engine", name="uq_tracked_kw"),
        Index("ix_tracked_kw_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("keywords.id", ondelete="SET NULL"), nullable=True)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    device: Mapped[str] = mapped_column(String(10), default="DESKTOP", nullable=False)
    engine: Mapped[str] = mapped_column(String(20), default="google", nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    observations: Mapped[list[RankObservation]] = relationship(
        back_populates="tracked", cascade="all,delete-orphan")


class RankObservation(Base):
    __tablename__ = "rank_observations"
    __table_args__ = (Index("ix_rank_obs_kw_time", "tracked_keyword_id", "observed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tracked_keyword_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracked_keywords.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ranking_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    serp_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=datetime.now,  # overridden per-row; migration uses server_default
    )

    tracked: Mapped[TrackedKeyword] = relationship(back_populates="observations")


# ------------------------------------------------------------------- SERP ---
class SerpSearch(Base, TimestampMixin):
    __tablename__ = "serp_searches"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_serp_cache_key"),
        Index("ix_serp_project_time", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), default="google", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    device: Mapped[str] = mapped_column(String(10), default="DESKTOP", nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_search_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    results: Mapped[list[SerpResult]] = relationship(
        back_populates="search", cascade="all,delete-orphan")
    features: Mapped[list[SerpFeature]] = relationship(
        back_populates="search", cascade="all,delete-orphan")


class SerpResult(Base):
    __tablename__ = "serp_results"
    __table_args__ = (
        UniqueConstraint("serp_search_id", "position", name="uq_serp_result_pos"),
        Index("ix_serp_result_domain", "serp_search_id", "domain"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    serp_search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("serp_searches.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_type: Mapped[str] = mapped_column(String(30), default="organic", nullable=False)
    feature_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    search: Mapped[SerpSearch] = relationship(back_populates="results")


class SerpFeature(Base):
    __tablename__ = "serp_features"
    __table_args__ = (Index("ix_serp_feature_search", "serp_search_id", "feature_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    serp_search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("serp_searches.id", ondelete="CASCADE"), nullable=False)
    feature_type: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    search: Mapped[SerpSearch] = relationship(back_populates="features")


# ------------------------------------------------------------------ crawler ---
class CrawlRun(Base, TimestampMixin):
    __tablename__ = "crawl_runs"
    __table_args__ = (Index("ix_crawl_runs_project_time", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issues_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    pages: Mapped[list[CrawlPage]] = relationship(
        back_populates="run", cascade="all,delete-orphan")


class CrawlPage(Base, TimestampMixin):
    __tablename__ = "crawl_pages"
    __table_args__ = (
        UniqueConstraint("crawl_run_id", "normalized_url", name="uq_crawl_page_run_url"),
        Index("ix_crawl_pages_status", "crawl_run_id", "status_code"),
        Index("ix_crawl_pages_hash", "crawl_run_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2000), nullable=False, index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    meta_description_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    robots_meta: Mapped[str | None] = mapped_column(String(500), nullable=True)
    h1_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    h1_text: Mapped[list | None] = mapped_column(JSON, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    images_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    images_missing_alt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    internal_links: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    external_links: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    redirect_target: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    indexability: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    is_noindex: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_nofollow: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_robots_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schema_presence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    open_graph: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    twitter_cards: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hreflang: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[CrawlRun] = relationship(back_populates="pages")


class CrawlLink(Base):
    __tablename__ = "crawl_links"
    __table_args__ = (Index("ix_crawl_links_run_to", "crawl_run_id", "normalized_to_url"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    from_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    to_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_to_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rel: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


# -------------------------------------------------------------------- audit ---
class AuditRule(Base, TimestampMixin):
    """Data-driven audit rule (seeded, toggleable)."""

    __tablename__ = "audit_rules"
    __table_args__ = (Index("ix_audit_rules_category", "category", "enabled"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditIssue(Base, TimestampMixin):
    """One rule firing on one crawl run (aggregated over instances)."""

    __tablename__ = "audit_issues"
    __table_args__ = (
        UniqueConstraint("crawl_run_id", "rule_id", name="uq_audit_issue_run_rule"),
        Index("ix_audit_issues_project_sev", "project_id", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_rules.id", ondelete="RESTRICT"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    instances: Mapped[list[AuditIssueInstance]] = relationship(
        back_populates="issue", cascade="all,delete-orphan")
    rule: Mapped[AuditRule] = relationship()


class AuditIssueInstance(Base):
    __tablename__ = "audit_issue_instances"
    __table_args__ = (Index("ix_audit_instances_issue", "issue_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_issues.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    issue: Mapped[AuditIssue] = relationship(back_populates="instances")


# ---------------------------------------------------------------------- GSC ---
class GscConnection(Base, TimestampMixin):
    __tablename__ = "gsc_connections"
    __table_args__ = (Index("ix_gsc_conn_org", "organization_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    google_account: Mapped[str | None] = mapped_column(String(320), nullable=True)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)

    properties: Mapped[list[GscProperty]] = relationship(
        back_populates="connection", cascade="all,delete-orphan")


class GscProperty(Base, TimestampMixin):
    __tablename__ = "gsc_properties"
    __table_args__ = (
        UniqueConstraint("connection_id", "site_url", name="uq_gsc_property"),
        Index("ix_gsc_prop_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gsc_connections.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    site_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    property_type: Mapped[str] = mapped_column(String(20), default="URL_PREFIX", nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped[GscConnection] = relationship(back_populates="properties")


class GscQueryData(Base):
    """Query-grain GSC history (one row per property/date/query/country/device)."""

    __tablename__ = "gsc_query_data"
    __table_args__ = (
        UniqueConstraint("property_id", "date", "query", "country", "device",
                         name="uq_gsc_query_grain"),
        Index("ix_gsc_query_prop_date", "property_id", "date"),
        Index("ix_gsc_query_text", "property_id", "query"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    property_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gsc_properties.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    query: Mapped[str] = mapped_column(String(1000), nullable=False)
    country: Mapped[str] = mapped_column(String(3), default="all", nullable=False)
    device: Mapped[str] = mapped_column(String(10), default="all", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class GscPageData(Base):
    """Page-grain GSC history (one row per property/date/page/country/device)."""

    __tablename__ = "gsc_page_data"
    __table_args__ = (
        UniqueConstraint("property_id", "date", "page", "country", "device",
                         name="uq_gsc_page_grain"),
        Index("ix_gsc_page_prop_date", "property_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    property_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gsc_properties.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    page: Mapped[str] = mapped_column(String(2000), nullable=False)
    country: Mapped[str] = mapped_column(String(3), default="all", nullable=False)
    device: Mapped[str] = mapped_column(String(10), default="all", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


# --------------------------------------------------------- recommendations ---
class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_reco_project_status", "project_id", "status"),
        Index("ix_reco_project_score", "project_id", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    impact: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    effort: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    related_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    related_keyword: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)


# ------------------------------------------------------------------ reports ---
class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_project_time", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    exports: Mapped[list[ReportExport]] = relationship(
        back_populates="report", cascade="all,delete-orphan")


class ReportExport(Base, TimestampMixin):
    __tablename__ = "report_exports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    report: Mapped[Report] = relationship(back_populates="exports")


# ----------------------------------------------------------------- providers ---
class ProviderAccount(Base, TimestampMixin):
    """User/org-configured provider credentials (secrets encrypted)."""

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "label",
                         name="uq_provider_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="CONFIGURED", nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderUsage(Base):
    """Metering for every billable provider operation."""

    __tablename__ = "provider_usage"
    __table_args__ = (Index("ix_provider_usage_org_time", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# -------------------------------------------------------------- notifications ---
class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
