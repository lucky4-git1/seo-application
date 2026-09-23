# Audit engine

`apps/api/app/audit/` — data-driven technical SEO rules + scoring.

## Rules

`rules.py` defines 26 rules as pure `check(ctx) -> [urls]` functions over a
crawl context (pages, inbound-link counts, ok-url set). Categories:
Crawlability, Indexability, Metadata, Content, Links, Images, Canonical,
Redirects, HTTPS, Structured Data, Performance, International.

Covered: SITE_DOWN (CRITICAL), BROKEN_PAGE, broken internal links, redirect
chains/loops, title missing/long/short/duplicate, meta missing/long/
duplicate, H1 missing/multiple, thin + duplicate content, orphan pages,
canonical missing/conflict, noindex, robots-blocked, missing alt, HTTP pages,
slow pages (>2 s), missing structured data, invalid hreflang.

Intentionally deferred (not silently dropped): MIXED_CONTENT (subresource
URLs not stored in v1 schema), MISSING_HREFLANG (noise on monolingual
sites — needs a multi-locale project setting), deep structured-data
validation.

A rule exception never breaks a run (skipped, run continues).

## Evaluation

`engine.run_audit(db, run_id)`: seeds `audit_rules` (idempotent upsert),
builds the context, evaluates enabled rules, writes `audit_issues` (one row
per run+rule, with message/why/recommendation) + up to 500
`audit_issue_instances` URLs each, updates `crawl_runs.issues_found` and
`health_score`. Re-running replaces previous results for the run.

## SEO Health Score (proprietary, transparent)

Per bucket: `100 − Σ severity_points × coverage`, coverage =
affected/pages_crawled, points = CRITICAL 60 / ERROR 25 / WARNING 10 /
NOTICE 3. Buckets weighted: crawlability 15%, indexability 15%, technical
20%, metadata 15%, content 15%, links 10%, performance 10%. Weights and
formula in `rules.py` (`BUCKET_WEIGHTS`, `score_bucket`, `health_score`);
the UI must show the methodology, never present it as a Google metric.

## API

`POST .../projects/{id}/audits` (202, enqueues), `GET .../audits` (history),
`GET .../audits/{id}` (run + live progress + severity counts + buckets),
`GET .../audits/{id}/issues` (filter by severity/category/search, sort by
severity/affected/recent, paginated), `GET .../issues/{id}/urls` (affected
URLs, paginated). All tenant-scoped; cross-org access returns 404/403
(tested).
