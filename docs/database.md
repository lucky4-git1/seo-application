# Database

Migrations (single source of truth: `apps/api/alembic/versions/`):

- `0001` — Phase 1: `users`, `organizations`, `organization_members`,
  `projects`, `jobs`, `audit_logs`.
- `0002` — SEO intelligence schema (Step 2): `domains`, `competitors`
  (relational — replaces `projects.competitors` JSON, backfilled),
  `keyword_clusters`, `keywords`, `keyword_metrics`, `keyword_intents`,
  `tracked_keywords`, `rank_observations`, `serp_searches`, `serp_results`,
  `serp_features`, `crawl_runs`, `crawl_pages`, `crawl_links`, `audit_rules`,
  `audit_issues`, `audit_issue_instances`, `gsc_connections`,
  `gsc_properties`, `gsc_query_data`, `gsc_page_data`, `recommendations`,
  `reports`, `report_exports`, `provider_accounts`, `provider_usage`,
  `notifications`; plus `jobs` hardening (`payload`, `result`,
  `started_at`, `finished_at`, composite indexes).

Principles: UUID PKs, FKs with CASCADE, explicit `op.create_index` (never
`Column(index=True)` inside migrations), unique constraints for
idempotency/dedup (`uq_tracked_kw`, `uq_serp_cache_key`, GSC grains),
`created_at/updated_at` with DB server defaults on new tables, soft-delete
where appropriate. Structured relational tables; JSON only for flexible
payloads (trends, SERP features, hreflang, report params, raw responses).

Models: `apps/api/app/models.py` (core) + `apps/api/app/models_seo.py`
(SEO). Types stay portable (no Postgres-only columns) so unit tests run on
SQLite with FK enforcement ON (`override_engine_for_tests`); the migration
targets PostgreSQL.

```powershell
cd apps/api
python -m alembic upgrade head
python -m pytest tests/ -q
```
