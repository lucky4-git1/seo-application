# SEO Intelligence Platform

Working SEO intelligence & digital marketing analytics platform
(Semrush-category). Monorepo: React + Tauri desktop + FastAPI + PostgreSQL
+ Redis + Celery.

> Philosophy: DATA → ANALYSIS → OPPORTUNITY → ACTION. Every module feeds the recommendation engine.
> No mock data policy: metrics come from DB / provider / crawler / GSC / calculation — never fabricated.

## What works

- **Projects as SEO workspaces**: overview dashboard (health, tracked
  keywords, issues, opportunities, GSC status), per-module sidebar.
- **Site crawler** (SSRF-guarded, robots/sitemap, politeness, page caps) +
  **26-rule technical audit engine** with transparent 0–100 health score.
- **Providers**: DataForSEO SERP + keyword-data live integration, encrypted
  credential vault, test-connection, 7-day SERP cache, usage metering.
- **Keywords**: research jobs, intent/difficulty/opportunity scoring,
  filtered tables, detail with trend + history.
- **SERP analysis**: live searches, history, result + feature detail.
- **Rank tracking**: tracked keywords, immediate + daily scheduled checks,
  movements, history sparklines.
- **Competitors + keyword gap** (missing/weak/shared/strong) with CSV export.
- **Google Search Console**: real OAuth, property picker, background sync,
  queries/pages analytics.
- **Recommendations**: 5-source engine with priority scoring + Action Center.
- **Reports**: SEO/Audit/Keyword/Ranking/Competitor reports as CSV/PDF via
  background jobs with expiring downloads.
- **Plans & limits** (FREE/PRO/BUSINESS enforcement + usage views),
  enforced rate limits, Argon2 auth, tenant isolation, audit logs.
- **Desktop**: Tauri 2 shell (compiles; installers need NSIS/WiX — see
  `docs/desktop.md`).

## Structure

```
apps/api      FastAPI backend (/api/v1, OpenAPI at /api/v1/docs)
apps/web      React+TS+Vite+Tailwind frontend (same build for web + Tauri)
apps/desktop  Tauri 2 shell (src-tauri compiles; backend URL in Settings)
services/*    retired — engines live in apps/api/app/{crawler,audit,...}
infrastructure/docker (+ deployment/)
docs/         architecture, database, crawler, audit-engine, providers,
              keyword-engine, serp-engine, competitor-engine, gsc,
              reports, billing, desktop, ...
```

## Quickstart (Docker)

```powershell
Copy-Item .env.example .env          # set JWT_SECRET (32+ chars, required)
docker compose up -d --build         # postgres, redis, api (:8000), worker, scheduler, web (:5173)
docker compose exec api python -m alembic upgrade head
```

Open http://localhost:5173 — register, create an organization + project,
run an audit. API docs: http://localhost:8000/api/v1/docs.
Demo account (seeded in dev): `demo@example.com` / `password123`.

Need DataForSEO? Add credentials in Settings → Provider settings (SERP +
keyword research stay honestly disabled until then). Need Google data?
Connect Search Console in the project (requires `GOOGLE_CLIENT_ID/SECRET`).

No-Docker Windows path, IPv6-loopback quirk, and port-conflict overrides:
see `docs/local-development.md`.

## API (selection)

- Auth/orgs/projects: `/auth/*`, `/organizations`, `.../projects`
- SEO: `.../projects/{id}/overview`, `.../audits*`, `.../keywords*`,
  `.../serp*`, `.../tracked-keywords*`, `.../competitors*`,
  `.../keyword-gap*`, `.../gsc*`, `.../recommendations*`, `.../reports*`
- Platform: `/providers`, `.../providers*`, `.../usage`, `.../limits`

## Verify

```powershell
cd apps/api; python -m pytest tests/ -q        # 83 tests
npm run typecheck --workspace apps/web; npm run build --workspace apps/web
```

Deliberately out of MVP: backlink/content/AI-visibility/traffic/market/
local/advertising suites, agency white-label, Stripe checkout (seam ready,
see `docs/billing.md`), global browsers/Playwright E2E (API journey test
covers the workflow in CI).
