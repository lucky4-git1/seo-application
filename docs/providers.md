# Providers

`apps/api/app/providers/` — vendor integrations behind Protocols.

## Abstraction

`base.py` defines `SERPProvider` / `KeywordProvider` Protocols with plain-dict
in/out (`SerpResponse`, `KeywordMetrics`) plus typed errors:
`ProviderError(code, retryable)`, `ProviderAuthError`, `ProviderQuotaError`.
Services (`app/serp.py`, `app/keyword_service.py`, `app/tasks.py`) depend only
on Protocols. Adding a vendor = new module + one entry in `registry.py`.

## Credential vault

`accounts.py` + `crypto.py`: secrets Fernet-encrypted (key derived from the
server secret) before storage in `provider_accounts`. API returns masked
previews only. Only OWNER/ADMIN may manage accounts. `test_connection`
makes the cheapest real vendor call and records ACTIVE/INVALID/ERROR.

Supported registry (`registry.py`): `dataforseo` (serp + keyword, live),
`google_ads` (keyword, planned — form disabled until the client ships).

## DataForSEO

`dataforseo.py`: Google Organic Live Advanced + Keyword-Data live endpoints
(search_volume, keywords_for_keywords), Basic auth, 90 s timeout, retry with
backoff on 429/5xx/network (never on auth/quota/billing errors). Vendor
status codes mapped: 401xx → auth, 402xx → quota. Response normalization is
pure and unit-tested (`tests/test_providers.py`); organic positions
renumbered 1..N, paid vs organic separated, SERP features extracted.

SERP caching (`app/serp.py`): persistent `serp_searches` keyed by
keyword/engine/country/language/device/location/provider/**project** (project
scope is deliberate — a global key leaked rows across tenants). 7-day TTL,
`force_refresh` bypass (used by rank checks). Every provider call writes a
`provider_usage` row.

## Endpoints

`GET /providers` (catalog), org `GET/POST/DELETE .../providers`,
`POST .../providers/{id}/test`, `GET .../usage` (30-day meter table).
