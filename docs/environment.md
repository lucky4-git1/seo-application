# Environment

Copy `.env.example` → `.env`. Never commit real secrets.

| Var | Required | Notes |
|-----|----------|-------|
| `DATABASE_URL` | yes | Postgres in dev/prod; `sqlite://` only for tests |
| `REDIS_URL` / `CELERY_*` | yes | Redis for cache, queues, rate limits, locks |
| `JWT_SECRET` | yes | 32+ chars, never logged |
| `CORS_ORIGINS` | yes | web + Tauri dev URLs |
| SERP / Google / NVIDIA / Stripe / S3 / Sentry | phase 4+ | platform-level only; user creds encrypted in DB |
