# Current-State Audit (2026-09-22)

Authoritative audit of the existing repository before the Semrush-class
transformation. Verified by reading every backend file (`apps/api`), every
frontend file (`apps/web`), and all infra/config (`docker-compose*`,
`infrastructure/`, `packages/`, `services/`, `scripts/`, `docs/`).

Stack live at audit time: postgres, redis, api (:8000), worker, scheduler,
web (:5173) — all healthy; `/ready` all-true; demo user + Acme org in DB.

---

## 1. What already works

- **Auth**: register/login/me, Argon2 hashing, JWT (HS256, 60-min), `auth/me`
  round-trip from the React client. (`apps/api/app/routers/auth.py`,
  `app/security.py`, `apps/web/src/lib/auth.tsx`)
- **Organizations + RBAC**: create/list orgs, add members, OWNER/ADMIN/MEMBER
  roles enforced per-endpoint via `require_org_role`. Tenant isolation tested
  (`tests/test_phase1.py`).
- **Projects**: full CRUD (soft delete), domain normalization
  (`https://www.Example.com/` → `example.com`), country/language/device,
  pagination. (`app/routers/projects.py`, `app/schemas.py:63-70`)
- **Audit logging**: `user.registered, login, organization.created,
  team.member_added, project.created/updated/deleted` → `audit_logs`.
- **Infra**: 6-service compose (postgres/redis/api/worker/scheduler/web),
  Alembic migration `0001`, pytest (4 passing), `tsc` clean, Swagger/ReDoc at
  `/api/v1/*`, JSON structured logging with request IDs, CORS + security
  headers, CI skeleton (pytest + typecheck).
- **Frontend**: login/register/dashboard/projects pages are real and call the
  API; auth guard, empty/error/skeleton states, backend-URL abstraction
  (`lib/api.ts`) shared with the Tauri shell.

## 2. What is partially implemented

- **Competitors**: only a free-form JSON `list[str]` on `projects.competitors`
  — no validation, normalization, dedup, or self-competitor check.
- **Jobs**: `jobs` table + `JOB_TYPES`/`JOB_STATUSES` constants exist, but zero
  Celery tasks, zero job API endpoints, and nothing ever writes to `jobs`.
- **Rate limiting**: `slowapi` Limiter configured but middleware/decorators
  never applied — no enforcement.
- **Health**: `/ready` checks DB + Redis but always returns HTTP 200 even when
  `ready:false`.
- **Plans/entitlements**: `Organization.plan` always `FREE`, never enforced;
  `User.is_admin` never read.
- **Desktop**: Tauri `tauri.conf.json` + backend-URL doc exist, but no welcome/
  settings screen, no store plugin, no installers built.
- **`packages/*`** (7 dirs) and **`services/*`** (6 of 7 dirs) are empty;
  `services/serp/providers.py` holds only `Protocol` interfaces.

## 3. What is missing (the actual product)

Everything that makes this an SEO platform: crawler, audit-rule engine,
health score, SERP provider + cache, keyword provider + research, intent/
difficulty/opportunity scoring, rank tracking + jobs, competitor entities +
keyword gap, GSC OAuth + sync + opportunities, recommendation engine, reports
(CSV/PDF) + background export jobs, provider settings (keys/Test/Disconnect),
usage metering, real-time job UI, charts, data tables with pagination/filters,
E2E tests. The project detail page is a static placeholder.

## 4. Broken/incomplete architecture

1. `packages/` + most of `services/` are empty — monorepo boundaries exist
   only on paper.
2. Rate limiting, job system, provider layer, analytics layer, recommendation
   engine: constants/docs only.
3. `logout` is a no-op; no refresh/revocation; `email_verified` never gated.
4. Transactions split inconsistently (service commits vs router commits).
5. Slug generation has a check-then-insert race (no `IntegrityError` retry).
6. `verify_password` catches only `VerifyMismatchError` (other hash errors →
   500); no rehash-upgrade path.
7. `ProjectUpdate` has no validators; `country` upper-cased without length
   check (DB `String(2)` → 500 on long input).
8. `list_projects` mixes archived/active, no stable ordering, no
   `response_model`; `Page` schema unused.
9. Frontend: `zod`/`clsx` installed but unused; no tests/lint config despite
   scripts; token in `localStorage`; `+ Org` uses blocking `prompt()`; N+1
   project queries on dashboard; `setBackendUrl`/`useProjectParams` dead.
10. No prod web image, `infrastructure/deployment/` + `infrastructure/
    migrations/` empty, no restart policies/resource limits in compose.

## 5. Database gaps

- Only 6 tables (`users, organizations, organization_members, projects, jobs,
  audit_logs`). All 25+ SEO tables absent (see transformation prompt §8).
- `projects.competitors` JSON text must become a relational `competitors`
  table (data migration + backfill).
- `jobs` lacks payload/result/started/finished timestamps/owner/idempotency.
- `audit_logs` lacks IP/UA/request_id.
- Roles/statuses/plans are free strings (no CHECK constraints).
- Alembic `0001` relies on `Column(index=True)` inside `op.create_table` for
  `jobs` indexes — silently ignored; must use `op.create_index`.
- No DB-level defaults for UUIDs/timestamps (raw-SQL inserts fail).
- Migration is Postgres-only and never exercised (tests use SQLite
  `create_all`); new models must stay SQLite-compatible for tests.

## 6. API gaps

No endpoints for: overview, audits (run/list/get/issues), keyword research/
list/detail, SERP search/list, tracked keywords, rankings, competitors,
keyword gap, GSC (connect/properties/sync/data), recommendations (+ status
PATCH), reports, providers (CRUD/test), usage, jobs (list/get/retry/cancel).
Full list required by spec in transformation prompt §41.

## 7. Frontend gaps

No project sidebar/command-center; routes for domain/keywords/serp/rankings/
gap/audit/competitors/gsc/recommendations/reports don't exist; no `<table>`,
charts, pagination, filters, sorting, CSV/PDF export, job-progress UI,
provider settings form, or GSC connect flow. `ProjectDetailPage` and
`SettingsPage` are static placeholders whose "Phase 2–9" copy must be removed
per transformation prompt §5.

## 8. Worker/job gaps

Zero `@celery.task` definitions; no beat schedule; no task routing/retries;
`jobs` table never written; no Flower/monitoring; worker image lacks
`slowapi`/`python-multipart` (irrelevant until tasks exist, but images will
need `lxml/bs4` for the crawler).

## 9. Provider integration gaps

No implementations — only `Protocol`s. No DataForSEO/Google-Ads/GSC/LLM
clients, no credential storage (encrypted), no Test-Connection, no caching
policy, no usage accounting, no `provider_accounts`/`provider_usage` tables.
`.env` has zero provider vars (correct for now).

## 10. Security issues (fix list for Step 19)

1. Dev DB creds (`seo/seo`) hardcoded in compose + baked into images.
2. Default `JWT_SECRET` placeholder; HS256 symmetric, no rotation/revocation.
3. `ADMIN` can grant `OWNER`; no last-owner protection; nonexistent org → 403
   (oracle) instead of 404; `add_member` → FK 500 on unknown org.
4. No SSRF protection yet (critical before crawler ships — §13).
5. Redis unauthenticated + host-exposed in base compose; no TLS.
6. Unhardened: no request timeouts on outbound calls (none exist yet), no
   secret encryption story, no rate-limit enforcement, `COOKIE_SECURE=false`
   default must not reach prod.
7. Supply chain: unpinned Docker/PyPI/npm installs, no lockfiles in images
   (`npm install` not `ci`), no secret scanning in CI.

## 11. Recommended implementation order

Exactly the transformation prompt §59 order, which this audit confirms:

1. ✅ This audit.
2. **Database** — all MVP tables + relational competitors + `jobs` hardening
   (this unblocks every engine).
3. **Crawler** (with SSRF guard from day one) — httpx+lxml/BS4, robots/sitemap,
   normalization, dedup, politeness.
4. **Audit engine** — data-driven rules, severities, health score, history.
5. **Project SEO dashboard + navigation** — command center wired to real
   tables (empty states until data exists); delete "future phase" copy.
6. **Provider abstraction** — interfaces + credential vault + usage metering.
7. **SERP provider** (DataForSEO) + Redis/persistent cache.
8. **Keyword provider** + normalization + intent/difficulty/opportunity.
9. **Keyword research UI**, 10. **Keyword overview**, 11. **Rank tracking**.
12. **Competitors**, 13. **Keyword gap**.
14. **GSC** (OAuth, sync, opportunities).
15. **Recommendations** (central engine fed by all modules).
16. **Reports** (CSV/PDF via jobs).
17. **Usage/billing foundations**, 18. **Desktop packaging**, 19. **Security
   audit** (fix §10 list + cross-tenant tests), 20. **E2E** (Playwright).

Rule for every step: database → migration → model → repository → service →
task (if needed) → API → client → UI (loading/error/empty) → tests. No fake
data, no dead buttons, no undocumented features (update `docs/` as built).
