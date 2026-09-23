# SERP engine + rank tracking

## SERP

`POST .../serp/search` (202, `FETCH_SERP` job: keyword, country, language,
device, location, depth 10–100, force_refresh) → `serp_searches` +
`serp_results` (organic renumbered, paid flagged) + `serp_features`.
`GET .../serp` history, `GET .../serp/{id}` full result + feature list.
UI: `serp/` + `serp/:searchId`. Unconfigured provider → honest
"not configured" message and zero fabricated rows (tested).

## Rank tracking

`POST .../tracked-keywords` creates (or reactivates) the tracked keyword and
enqueues an immediate `TRACK_RANK` check; daily Celery Beat
(`track-scheduled-ranks-daily`, 03:00 UTC) refreshes every active keyword
whose project has a SERP provider, skipping the rest. Each check forces a
fresh SERP, finds the project domain's best organic rank/URL (`find_rank`
with www/subdomain folding), and stores a `rank_observations` row — including
`rank: null` when absent (a real signal, not an error).

`GET .../tracked-keywords`: current/previous/change/best/worst per keyword.
`GET .../tracked-keywords/{id}/history`: observations for charts (UI draws an
inline SVG sparkline from real points). `DELETE` deactivates (history kept).
UI: `rankings/` route with add form, movement table, per-row history.
