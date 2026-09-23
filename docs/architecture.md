# Architecture

```
UI (React, web + Tauri) → HTTPS → API (FastAPI /api/v1) → Services → Repositories → PostgreSQL
                                                              ↘ Celery+Redis (jobs) → workers
```

Rules:
- Route → service → repository → DB. No business logic in routes.
- Providers live in `infrastructure/providers/` (Phase 4+), behind interfaces.
- Data flow: EXTERNAL → ADAPTER → RAW → NORMALIZE → VALIDATE → DB → ANALYTICS → SCORING → RECOMMENDATIONS → API → UI.
- Frontend never calls providers directly. Server state via TanStack Query only.
