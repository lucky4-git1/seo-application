# Competitors + keyword gap

## Competitors

Relational `competitors` rows per project (normalized domain, unique per
project, self-domain and invalid input rejected with 400, removal is
deactivation to preserve history). The legacy `projects.competitors` JSON is
write-dead — the UI never sends it.

API: `POST/GET .../competitors`, `DELETE .../competitors/{id}`,
`GET .../competitors/{id}/overview` (SERP appearances, avg position, top
pages — computed from stored `serp_*` rows only). UI: `competitors/` route.

## Keyword gap (core)

`GET .../keyword-gap` computes live from stored observations — no implicit
provider calls, nothing estimated:

- candidate set = active tracked keywords
- your rank = latest `rank_observations` (null = unranked)
- competitor rank = latest stored `serp_searches` row for the same
  keyword/country/device containing the competitor domain (null = no data)
- buckets: **missing** (you null, competitor ranked), **weak** (you rank
  worse than best competitor), **strong** (you best or competitor absent),
  **shared** (everything else)
- enriched with stored metric views (volume/difficulty/intent) and the
  platform opportunity score; filters: bucket, intent, min volume, max
  difficulty; sorted by opportunity; paginated
- `GET .../keyword-gap/export` returns the same computation as CSV
  (server-side, authenticated)

Nulls are honest: a competitor with no stored SERP coverage shows null with
the UI stating data is unavailable — never a fabricated rank.

UI: `keyword-gap/` route (competitor picker, bucket filter, per-competitor
rank columns, opportunity sort, authed CSV export), linked from the
competitor table and the project nav.
