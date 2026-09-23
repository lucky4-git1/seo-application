# Local development

## Option A — Docker (recommended where Docker works)

1. `Copy-Item .env.example .env` and set `JWT_SECRET` (32+ chars).
2. `docker compose up --build`
3. `cd apps/api; python -m alembic upgrade head`
4. `npm install; npm run dev:web` (from repo root) — serves web on http://localhost:5173
5. Tests: `cd apps/api; python -m pytest`

## Option B — No Docker (native Windows)

Scripts live in `scripts/`; logs and the Postgres data dir live under
`%LOCALAPPDATA%\seo-app\`.

1. `Copy-Item .env.example .env` and set `JWT_SECRET` (32+ chars).
   Point `DATABASE_URL` at your Postgres, e.g.
   `postgresql+psycopg://seo:seo@127.0.0.1:5434/seo`.
   NOTE: use `127.0.0.1`, not `localhost` — on some Windows machines the
   IPv6 loopback (`::1`) black-holes connections and every DB connect hangs
   until it falls back to IPv4.
2. Postgres: if port 5432 is taken by another install, init a user-space
   cluster (PostgreSQL 18 `bin\initdb.exe -D <dir> -U seo --pwfile=...`),
   set `port = 5434` in `postgresql.conf`, start with `pg_ctl -D <dir> -l
   <logfile> start`. Or run `scripts\run-pg.cmd`.
3. Backend deps: `pip install` the list in `apps/api/pyproject.toml`
   (`pip install -e ./apps/api` also works since `[tool.setuptools]
   packages = ["app"]`).
4. `cd apps/api; python -m alembic upgrade head`
5. Tests: `python -m pytest tests/test_phase1.py -q`
6. API: `scripts\run-api.cmd` → http://127.0.0.1:8000 (`/api/v1/health`,
   `/api/v1/docs`).
7. Web: `npm install` once at root, then `npm run dev:web` (root) or
   `npm run dev` (inside `apps/web`). NOTE: repo root has no `dev` script —
   bare `npm run dev` at root fails with "Missing script". Or run
   `scripts\run-web.cmd` (port 5200).
8. Auto-start on logon: copy `scripts\start-stack.cmd` (or a shortcut) to
   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.
9. Redis is optional for Phase 1 (API runs; `/ready` reports `redis:false`).
   The Celery worker needs a real Redis broker for background jobs.

## Ports used by this repo (defaults)

API :8000 · Web :5173 (dev) · Postgres :5432 (docker) / :5434 (local
override, see `docker-compose.override.yml`) · Redis :6379.
If 5173 is taken by another project, run web on another port, e.g.
`npm run dev --workspace apps/web -- --port 5200 --strictPort`, and add the
origin to `CORS_ORIGINS` in `.env`.
