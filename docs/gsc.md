# Search Console

Real Google OAuth 2.0 + Search Analytics API. No invented rows — every number
comes from `searchanalytics.query`.

## Connect flow

1. `GET .../gsc/auth-url` → Google consent URL (15-min signed state binding
   org/project/user). Requires `GOOGLE_CLIENT_ID/SECRET` (+ optional
   `GOOGLE_REDIRECT_URI`, default `http://localhost:8000/api/v1/gsc/oauth/callback`).
   Without them: honest **503**, never a fake URL.
2. User consents → `GET /api/v1/gsc/oauth/callback?code&state` → code
   exchange → tokens Fernet-encrypted into `gsc_connections` → properties
   listed into `gsc_properties`. HTML success page for humans, JSON for API
   clients (content negotiation).
3. UI lists connections/properties → `POST .../gsc/select` links one property
   to the project (`is_selected`; one selected per project).
4. `POST .../gsc/sync` (202, `SYNC_GSC` job) pulls
   `[date, query, country, device]` + `[date, page, country, device]` for the
   last N days (7–365, default 90), paginated, upserted on grain uniques —
   re-syncs refresh, never duplicate. Access tokens auto-refresh mid-sync and
   persist the new token.
5. `DELETE .../gsc/connections/{id}` (OWNER/ADMIN) tombstones tokens then
   cascade-deletes properties + data.

Tradeoff (documented): no full query×country×device cube in v1 — the
combinatorial explosion is deferred; country/device arrive as returned
("all" unless Google splits them).

## Reads

`GET .../gsc/overview` (totals + daily clicks/impressions series),
`GET .../gsc/queries` and `.../gsc/pages` (search, sort, paginate).
UI: `gsc/` route — connect card, property picker, sync with polling,
KPI cards, impressions chart (real points), query/page tables.
