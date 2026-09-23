# Keyword engine

Pipeline: seed → provider suggestions → `normalize_keyword` dedup (case,
whitespace, Unicode NFKC, punctuation) → `keywords` row per
(org, normalized, country, language) → `keyword_metrics` snapshot per fetch →
heuristic `keyword_intents` → scored views.

## Intent (spec §20)

Deterministic marker rules, first match wins: transactional (buy, price,
order…), local (near me, nearby, open now…), commercial (best, vs, review…),
navigational (login, official site…), informational fallback incl.
question-form detection. Returns confidence 0–1. AI re-classification of
uncertain cases is future work.

## Platform Keyword Difficulty 0–100 (estimate, documented in UI)

`40%` top-10 saturation × `35%` vendor competition × `25%` demand tier.
Labeled as the platform's estimate, never a vendor/Google metric.

## Opportunity Score 0–100

`demand(log volume) × achievability(1 − difficulty) × intent value
(transactional 1.0 … navigational 0.5) × proximity bonus (ranks 4–15)`.
Drives opportunity sorting.

## API + UI

`POST .../keywords/research` (202, `FETCH_KEYWORDS` job),
`GET .../keywords` (search, intent/volume/difficulty filters, sort by
opportunity/volume/difficulty/A–Z, paginated, CSV export of view),
`GET .../keywords/{id}` (latest metrics + trend + 30-row history).
UI: `keywords/` + `keywords/:keywordId` routes.
