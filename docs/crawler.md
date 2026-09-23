# Crawler

`apps/api/app/crawler/` — polite, bounded, SSRF-guarded site crawler.
Runs in the Celery worker via `seo.run_audit` (`app/tasks.py`); never in HTTP.

## Flow

`POST .../audits` → `crawl_runs` row (PENDING) + `jobs` row → task →
`run_crawl()` → `run_audit()` (see `audit-engine.md`).

1. Validate seed domain (SSRF check). Status → RUNNING.
2. `discover_seeds()`: fetch `/robots.txt` (Disallow + crawl-delay + Sitemap
   lines), then sitemap index → urlset (nested, depth ≤ 2).
3. BFS frontier: homepage first, then sitemap URLs, then discovered internal
   links. Same-site only (www-folded hostname match; subdomains are separate
   sites). `robots.txt` Disallow honored per path. Politeness delay
   (≥250 ms, more if crawl-delay says so).
4. Fetch each URL (`fetch.py`): manual redirect walk (max 5, every hop
   re-validated), 10 s connect / 15 s read timeouts, 5 MB body cap with early
   abort, non-HTML stored without parsing.
5. Parse HTML (`parse.py`, BeautifulSoup/lxml): title, meta description,
   canonical, robots meta, H1s, word count, images + missing alt, internal/
   external link counts, noindex/nofollow, JSON-LD types, Open Graph, Twitter
   cards, hreflang, content hash (duplicate detection). Best-effort — malformed
   HTML never crashes a crawl.
6. Persist `crawl_pages` (every fetch incl. errors/redirects/robots-blocked)
   + `crawl_links`. Counters (`pages_discovered/pages_crawled`) commit every
   5 pages so progress is real.

## Safety (mandatory, tested in `tests/test_crawler.py`)

`crawler/safety.py`: http/https only, no userinfo, host required; blocks
`localhost` variants; resolves DNS and rejects any non-globally-routable IP
(private, loopback, link-local incl. 169.254.169.254 metadata, reserved,
multicast, `0.0.0.0`). Redirect targets re-validated hop by hop.

## Limits

`DEFAULT_MAX_PAGES = 200`, hard cap 500 per run (`max_pages` in POST body,
1–500). URL length 2000. Sitemap seeds capped at 10 000 URLs.

## Image split

Parser deps (`beautifulsoup4`, `lxml`) live in the **worker** image only.
The API enqueues by task name (`celery.send_task`) and never imports the
crawler stack — verified by an import test in the api container.
