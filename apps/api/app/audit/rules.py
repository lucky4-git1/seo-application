"""Data-driven audit rules (Step 4, spec §14).

Each rule is a pure check over a crawl context — no DB, no network — so the
whole engine is unit-testable. Rule metadata (code/name/severity/category/
recommendation) doubles as the seed for the audit_rules table.

Severity: CRITICAL > ERROR > WARNING > NOTICE.
check(ctx) -> list of affected page URLs (may be empty).

Deferred intentionally (documented, not silently dropped):
- MIXED_CONTENT: subresource URLs are not stored in v1 crawl schema.
- MISSING_HREFLANG: fires on every monolingual site; needs multi-locale
  site config (a project setting that does not exist yet).
- Malformed structured-data validation: shallow detection only.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

TITLE_TOO_LONG = 60
TITLE_TOO_SHORT = 30
META_TOO_LONG = 160
THIN_WORDS = 300
SLOW_MS = 2000
MAX_STORED_INSTANCES = 500


@dataclass
class Ctx:
    pages: list[dict] = field(default_factory=list)   # parsed page dicts
    inbound: Counter = field(default_factory=Counter)  # normalized_url -> inbound count
    by_url: dict = field(default_factory=dict)         # normalized_url -> page
    ok_urls: set = field(default_factory=set)          # normalized urls with status 200
    run: dict = field(default_factory=dict)            # {"pages_crawled": int}


def _indexable(p: dict) -> bool:
    return (p.get("status_code") == 200 and not p.get("is_noindex")
            and not p.get("is_robots_blocked"))


def _html_ok(pages: list[dict]) -> list[dict]:
    return [p for p in pages if p.get("status_code") == 200]


Check = Callable[[Ctx], list[str]]


@dataclass
class Rule:
    code: str
    name: str
    category: str
    severity: str
    description: str
    why_it_matters: str
    recommendation: str
    check: Check


def _r(code, name, category, severity, description, why, recommendation, check) -> Rule:
    return Rule(code, name, category, severity, description, why, recommendation, check)


def _dup_urls(pages: list[dict], key: str) -> list[str]:
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for p in _html_ok(pages):
        val = (p.get(key) or "").strip().lower()
        if not val:
            continue
        if val in seen:
            dupes.append(p["url"])
            if seen[val] not in dupes:
                dupes.append(seen[val])
        else:
            seen[val] = p["url"]
    return sorted(set(dupes))


RULES: list[Rule] = [
    _r("SITE_DOWN", "Homepage unreachable", "Crawlability", "CRITICAL",
       "The homepage could not be fetched successfully.",
       "If crawlers cannot reach the homepage, the whole site is effectively down.",
       "Restore the homepage immediately (hosting, DNS, TLS, firewall) and re-run the audit.",
       lambda c: [p["url"] for p in c.pages
                  if p.get("depth", 1) == 0 and (p.get("status_code") or 0) >= 500]),

    _r("BROKEN_PAGE", "Broken page (4xx/5xx)", "Crawlability", "ERROR",
       "Page returns a client or server error.",
       "Broken pages waste crawl budget and leak link equity.",
       "Fix, redirect (301) to the closest live page, or remove internal links to it.",
       lambda c: [p["url"] for p in c.pages
                  if (p.get("status_code") or 0) >= 400]),

    _r("TITLE_MISSING", "Missing title tag", "Metadata", "ERROR",
       "Page has no <title>.",
       "The title is the strongest on-page relevance signal and the SERP headline.",
       "Write a unique, descriptive title (30–60 characters) for every indexable page.",
       lambda c: [p["url"] for p in _html_ok(c.pages) if not (p.get("title") or "").strip()]),

    _r("TITLE_TOO_LONG", "Title too long (>60 chars)", "Metadata", "WARNING",
       "Title exceeds ~60 characters and will be truncated in SERPs.",
       "Truncated titles lose clicks and dilute the headline message.",
       "Shorten to 30–60 characters, primary keyword first.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if len(p.get("title") or "") > TITLE_TOO_LONG]),

    _r("TITLE_TOO_SHORT", "Title too short (<30 chars)", "Metadata", "WARNING",
       "Title is unusually short and likely undescriptive.",
       "Short titles under-use the headline slot and rank for fewer variants.",
       "Expand to 30–60 descriptive characters.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if 0 < len(p.get("title") or "") < TITLE_TOO_SHORT]),

    _r("DUPLICATE_TITLE", "Duplicate title tag", "Metadata", "ERROR",
       "Two or more pages share the same title.",
       "Duplicate titles confuse ranking (keyword cannibalization) and SERP choice.",
       "Give every indexable page a unique title; consolidate near-duplicate pages.",
       lambda c: _dup_urls(c.pages, "title")),

    _r("META_DESCRIPTION_MISSING", "Missing meta description", "Metadata", "ERROR",
       "Page has no meta description.",
       "The description is the SERP sales pitch; missing ones depress CTR.",
       "Write a unique 120–160 character description with a call to action.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if not (p.get("meta_description") or "").strip()]),

    _r("META_DESCRIPTION_TOO_LONG", "Meta description too long (>160 chars)", "Metadata",
       "WARNING", "Description exceeds ~160 characters and will be truncated.",
       "Truncated descriptions waste the pitch and can look sloppy in SERPs.",
       "Shorten to 120–160 characters.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if len(p.get("meta_description") or "") > META_TOO_LONG]),

    _r("DUPLICATE_META_DESCRIPTION", "Duplicate meta description", "Metadata", "ERROR",
       "Two or more pages share the same meta description.",
       "Duplicate descriptions reduce SERP differentiation and CTR.",
       "Write a unique description per indexable page.",
       lambda c: _dup_urls(c.pages, "meta_description")),

    _r("H1_MISSING", "Missing H1", "Content", "ERROR",
       "Page has no H1 heading.",
       "The H1 frames page topic for users and crawlers.",
       "Add exactly one descriptive H1 per page.",
       lambda c: [p["url"] for p in _html_ok(c.pages) if (p.get("h1_count") or 0) == 0]),

    _r("MULTIPLE_H1", "Multiple H1 tags", "Content", "WARNING",
       "Page contains more than one H1.",
       "Multiple H1s dilute topical focus (tolerable in HTML5, still worth cleaning).",
       "Keep one H1; demote the rest to H2.",
       lambda c: [p["url"] for p in _html_ok(c.pages) if (p.get("h1_count") or 0) > 1]),

    _r("THIN_CONTENT", "Thin content (<300 words)", "Content", "WARNING",
       "Indexable page has very little text.",
       "Thin pages rarely satisfy intent and struggle to rank.",
       "Expand with genuinely useful content or noindex/consolidate the page.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if _indexable(p) and (p.get("word_count") or 0) < THIN_WORDS]),

    _r("DUPLICATE_CONTENT", "Duplicate content", "Content", "ERROR",
       "Two or more pages have identical body content.",
       "Duplicates split ranking signals across URLs.",
       "Canonicalize, redirect, or differentiate the pages.",
       lambda c: _dup_urls(c.pages, "content_hash")),

    _r("ORPHAN_PAGE", "Orphan page (no internal inbound links)", "Links", "WARNING",
       "Crawled page has no internal links pointing to it (excluding homepage).",
       "Orphan pages get little crawl budget and pass no context.",
       "Link to it from relevant hub/category pages or remove it.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if p.get("depth", 1) > 0 and c.inbound.get(p.get("normalized_url"), 0) == 0]),

    _r("BROKEN_INTERNAL_LINK", "Page links to a broken internal URL", "Links", "ERROR",
       "A page links to an internal URL that returned 4xx/5xx in this crawl.",
       "Broken internal links hurt UX and waste crawl budget.",
       "Update or remove the link.",
       lambda c: _broken_link_sources(c)),

    _r("REDIRECT_CHAIN", "Redirect chain", "Redirects", "WARNING",
       "Page redirects to a URL that itself redirects.",
       "Chains slow crawlers and leak equity with every hop.",
       "Point the source directly at the final destination.",
       lambda c: _redirect_targets(c, chained=True)),

    _r("REDIRECT_LOOP", "Redirect loop", "Redirects", "ERROR",
       "Redirect target loops back (A→B→A or self-redirect).",
       "Loops are uncrawlable and unusable.",
       "Break the cycle so every redirect resolves to a 200 page.",
       lambda c: _redirect_targets(c, chained=False)),

    _r("CANONICAL_MISSING", "Missing canonical on indexable page", "Canonical", "WARNING",
       "Indexable page declares no canonical URL.",
       "Without a canonical, duplicates and parameter variants split signals.",
       "Add a self-referencing canonical to every indexable page.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if _indexable(p) and not (p.get("canonical") or "").strip()]),

    _r("CANONICAL_CONFLICT", "Canonical points to uncrawled/broken URL", "Canonical",
       "ERROR", "Canonical target was not crawled successfully in this run.",
       "A canonical to a dead or uncrawled URL strands the page's signals.",
       "Point the canonical at the correct live URL.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if (p.get("canonical_normalized") or "") and
                  p["canonical_normalized"] not in c.ok_urls]),

    _r("NOINDEX_PAGE", "Noindex page discovered", "Indexability", "WARNING",
       "Crawled page carries a noindex directive.",
       "Noindex pages collect no organic traffic; unexpected ones are leaks.",
       "Verify intent; remove noindex or stop linking/crawling the page.",
       lambda c: [p["url"] for p in c.pages if p.get("is_noindex")]),

    _r("ROBOTS_BLOCKED", "URL blocked by robots.txt", "Crawlability", "WARNING",
       "URL was skipped because robots.txt disallows it.",
       "Blocked URLs that are linked or important waste discovery.",
       "Allow the URL or remove references to it.",
       lambda c: [p["url"] for p in c.pages if p.get("is_robots_blocked")]),

    _r("MISSING_IMAGE_ALT", "Images missing alt text", "Images", "WARNING",
       "Page contains <img> without usable alt text.",
       "Alt text aids accessibility and image search.",
       "Add descriptive alt text to content images.",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if (p.get("images_missing_alt") or 0) > 0]),

    _r("HTTP_PAGE", "Page served over HTTP", "HTTPS", "ERROR",
       "Page URL uses http:// instead of https://.",
       "HTTP pages trigger browser warnings and split signals.",
       "Serve everything over HTTPS with HSTS and redirect HTTP→HTTPS.",
       lambda c: [p["url"] for p in c.pages if (p.get("url") or "").startswith("http://")]),

    _r("SLOW_PAGE", "Slow page (>2s server response)", "Performance", "WARNING",
       "Server took over 2 seconds to respond.",
       "Slow responses hurt crawl budget and user experience.",
       "Profile server response (caching, DB, hosting) and re-test.",
       lambda c: [p["url"] for p in c.pages
                  if (p.get("response_time_ms") or 0) > SLOW_MS]),

    _r("MISSING_STRUCTURED_DATA", "No structured data on indexable page", "Structured Data",
       "NOTICE", "Indexable page declares no JSON-LD/schema.org types.",
       "Eligible markup can unlock rich results.",
       "Add relevant schema.org types (Article, Product, FAQ, BreadcrumbList…).",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if _indexable(p) and not (p.get("schema_presence") or [])]),

    _r("INVALID_HREFLANG", "Invalid hreflang value", "International", "WARNING",
       "hreflang tag uses a malformed language/region code.",
       "Invalid hreflang is ignored, breaking geo-targeting.",
       "Use valid ISO codes (ll or ll-CC).",
       lambda c: [p["url"] for p in _html_ok(c.pages)
                  if any(not _valid_hreflang(k) for k in (p.get("hreflang") or {}))]),
]


def _broken_link_sources(ctx: Ctx) -> list[str]:
    broken_targets = {p.get("normalized_url") for p in ctx.pages
                      if (p.get("status_code") or 0) >= 400}
    return sorted({p["url"] for p in _html_ok(ctx.pages)
                   if any(l.get("normalized_to_url") in broken_targets
                          for l in p.get("out_links", []))})


def _redirect_targets(ctx: Ctx, *, chained: bool) -> list[str]:
    targets = {p.get("normalized_url"): (p.get("redirect_target_normalized") or "")
               for p in ctx.pages if p.get("redirect_target_normalized")}
    out: list[str] = []
    for src, tgt in targets.items():
        if not tgt:
            continue
        if chained and tgt in targets:
            out.append(ctx.by_url.get(src, {}).get("url", src))
        if not chained and (tgt == src or targets.get(tgt) == src):
            out.append(ctx.by_url.get(src, {}).get("url", src))
    return sorted(set(out))


def _valid_hreflang(code: str) -> bool:
    import re
    if code in ("x-default",):
        return True
    return bool(re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", code or ""))


# ------------------------------------------------------------------ scoring ---
BUCKET_WEIGHTS = {
    "crawlability": 0.15,
    "indexability": 0.15,
    "technical": 0.20,
    "metadata": 0.15,
    "content": 0.15,
    "links": 0.10,
    "performance": 0.10,
}

CATEGORY_TO_BUCKET = {
    "Crawlability": "crawlability",
    "Redirects": "crawlability",
    "Indexability": "indexability",
    "Canonical": "indexability",
    "International": "indexability",
    "HTTPS": "technical",
    "Structured Data": "technical",
    "Metadata": "metadata",
    "Content": "content",
    "Links": "links",
    "Images": "links",
    "Performance": "performance",
}

SEVERITY_POINTS = {"CRITICAL": 60.0, "ERROR": 25.0, "WARNING": 10.0, "NOTICE": 3.0}


def score_bucket(issues: list[dict], pages_crawled: int) -> float:
    """Transparent bucket score: 100 minus severity-weighted coverage.

    issues: [{"severity": ..., "affected_count": ...}]
    """
    pages = max(1, pages_crawled)
    deduction = 0.0
    for issue in issues:
        coverage = min(1.0, (issue.get("affected_count", 0) or 0) / pages)
        deduction += SEVERITY_POINTS.get(issue.get("severity", "NOTICE"), 3.0) * coverage
    return round(max(0.0, 100.0 - deduction), 1)


def health_score(bucket_scores: dict[str, float]) -> float:
    """Weighted 0–100 SEO Health Score (weights in BUCKET_WEIGHTS)."""
    return round(sum(bucket_scores.get(b, 0.0) * w for b, w in BUCKET_WEIGHTS.items()), 1)


def rule_index() -> dict[str, Rule]:
    return {r.code: r for r in RULES}
