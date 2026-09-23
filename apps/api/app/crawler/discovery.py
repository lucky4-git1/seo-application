"""robots.txt + XML sitemap discovery (spec §11).

Minimal dependency-free parsing: sufficient for crawl gating (Disallow +
crawl-delay for our UA) and URL seeding (urlset + sitemapindex, nested).
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from app.crawler.fetch import FetchResult, fetch_url, is_html  # noqa: F401

UA_TOKEN = "seobot"
MAX_SITEMAP_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_URLS = 10000


def parse_robots(body: str) -> dict:
    """Parse robots.txt into {disallows: [...], crawl_delay: float|None, sitemaps: [...] }."""
    disallows: list[str] = []
    global_disallows: list[str] = []
    sitemaps: list[str] = []
    crawl_delay: float | None = None
    in_relevant_group = False
    seen_ua = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            seen_ua = True
            ua = value.lower()
            in_relevant_group = ua in ("*", UA_TOKEN)
        elif field == "disallow" and in_relevant_group and value:
            disallows.append(value)
        elif field == "disallow" and not seen_ua and value:
            global_disallows.append(value)
        elif field == "crawl-delay" and in_relevant_group:
            try:
                crawl_delay = max(crawl_delay or 0.0, float(value))
            except ValueError:
                pass
        elif field == "sitemap" and value:
            sitemaps.append(value)
    return {
        "disallows": disallows or global_disallows,
        "crawl_delay": crawl_delay,
        "sitemaps": sitemaps,
    }


def is_allowed(path: str, disallows: list[str]) -> bool:
    for rule in disallows:
        if path == rule or path.startswith(rule.rstrip("*")):
            # Allow lines are rare in the wild for our scope; a Disallow
            # prefix match blocks (conservative = crawler-safe).
            return False
    return True


def parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, nested_sitemap_urls) from urlset/sitemapindex XML."""
    try:
        root = ET.fromstring(body[:MAX_SITEMAP_BYTES])
    except ET.ParseError:
        return [], []

    def tag(el) -> str:
        return el.tag.split("}", 1)[-1].lower()

    pages: list[str] = []
    nested: list[str] = []
    kind = tag(root)
    if kind == "urlset":
        for url_el in root.iter():
            if tag(url_el) == "loc" and url_el.text:
                pages.append(url_el.text.strip())
                if len(pages) >= MAX_SITEMAP_URLS:
                    break
    elif kind == "sitemapindex":
        for sm in root.iter():
            if tag(sm) == "loc" and sm.text:
                nested.append(sm.text.strip())
                if len(nested) >= 100:
                    break
    return pages, nested


def discover_seeds(base_url: str, *, max_sitemap_depth: int = 2) -> dict:
    """Fetch robots.txt + sitemaps for a site. Returns seeds + robots rules.

    Never raises on absence (missing robots/sitemap is normal); SSRF blocks
    surface as error text.
    """
    parts = urlparse(base_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    out = {"robots": {"disallows": [], "crawl_delay": None, "sitemaps": []},
           "seed_urls": [], "error": None}
    try:
        res = fetch_url(origin + "/robots.txt")
    except Exception as exc:  # defensive: fetch_url already catches most
        out["error"] = str(exc)
        return out
    if res.error and res.status_code == 0 and "blocked" in (res.error or ""):
        out["error"] = res.error
        return out
    if res.status_code == 200 and res.body:
        try:
            out["robots"] = parse_robots(res.body.decode("utf-8", "ignore"))
        except Exception:
            pass
    candidates = list(out["robots"]["sitemaps"]) or [origin + "/sitemap.xml"]
    seen: set[str] = set()
    queue = [(u, 0) for u in candidates]
    while queue and len(out["seed_urls"]) < MAX_SITEMAP_URLS:
        sm_url, depth = queue.pop(0)
        if sm_url in seen or depth > max_sitemap_depth:
            continue
        seen.add(sm_url)
        try:
            sm = fetch_url(sm_url)
        except Exception:
            continue
        if sm.error or sm.status_code != 200 or not sm.body:
            continue
        pages, nested = parse_sitemap(sm.body)
        out["seed_urls"].extend(pages)
        queue.extend((u, depth + 1) for u in nested)
        time.sleep(0.1)
    return out
