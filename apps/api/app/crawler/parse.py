"""HTML → SEO signal extraction (spec §12/§20).

Pure function: (final_url, body bytes, content_type) -> dict matching the
CrawlPage columns + discovered outbound links. No network, no DB.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.crawler.normalize import fold_www, normalize_url

WS_RE = re.compile(r"\s+")
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg", "canvas"}


def _text(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    for el in soup.find_all(string=True):
        if el.parent and el.parent.name not in SKIP_TEXT_TAGS:
            t = el.strip()
            if t:
                parts.append(t)
    return WS_RE.sub(" ", " ".join(parts)).strip()


def content_hash(text: str) -> str:
    canonical = WS_RE.sub(" ", text.lower()).strip()
    return hashlib.sha256(canonical.encode("utf-8", "ignore")).hexdigest()


def parse_html(final_url: str, body: bytes, content_type: str = "text/html") -> dict:
    """Extract SEO signals. Never raises on malformed HTML (best-effort)."""
    try:
        soup = BeautifulSoup(body, "lxml")
    except Exception:
        return _empty(final_url)

    host = (urlparse(final_url).hostname or "").lower()

    def _meta(name: str = "", prop: str = "") -> str | None:
        if name:
            tag = soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        if prop:
            tag = soup.find("meta", attrs={"property": prop})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta_desc = _meta("description")
    robots_meta = _meta("robots")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else None
    if canonical:
        canonical = urljoin(final_url, canonical)

    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    robots_lc = (robots_meta or "").lower()
    is_noindex = "noindex" in robots_lc

    images = soup.find_all("img")
    missing_alt = sum(1 for i in images if not (i.get("alt") or "").strip())

    internal = external = 0
    links: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = urljoin(final_url, href)
        if urlparse(abs_url).scheme not in ("http", "https"):
            continue
        link_host = (urlparse(abs_url).hostname or "").lower()
        is_internal = fold_www(link_host) == fold_www(host) and bool(host)
        internal += is_internal
        external += not is_internal
        rel = a.get("rel")
        links.append({
            "from_url": final_url,
            "to_url": abs_url,
            "normalized_to_url": normalize_url(abs_url),
            "is_internal": is_internal,
            "rel": " ".join(rel) if isinstance(rel, list) else (rel or None),
        })

    schema_types: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or ""
        for m in re.finditer(r'"@type"\s*:\s*"([^"]+)"', raw):
            schema_types.append(m.group(1))

    og = {t.get("property", "")[3:]: (t.get("content") or "").strip()
          for t in soup.find_all("meta", property=re.compile(r"^og:"))}
    tw = {t.get("name", "")[8:]: (t.get("content") or "").strip()
          for t in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")})}
    hreflang = {l.get("hreflang", "").lower(): (l.get("href") or "").strip()
                for l in soup.find_all("link", hreflang=True)}

    lang = None
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        lang = html_tag["lang"][:10]

    visible = _text(soup)
    return {
        "title": title[:1000] if title else None,
        "title_length": len(title) if title else 0,
        "meta_description": meta_desc[:2000] if meta_desc else None,
        "meta_description_length": len(meta_desc) if meta_desc else 0,
        "canonical": canonical[:2000] if canonical else None,
        "robots_meta": robots_meta[:500] if robots_meta else None,
        "h1_count": len(h1s),
        "h1_text": h1s[:20],
        "word_count": len(visible.split()),
        "language": lang,
        "images_count": len(images),
        "images_missing_alt": missing_alt,
        "internal_links": internal,
        "external_links": external,
        "is_noindex": is_noindex,
        "is_nofollow": "nofollow" in robots_lc,
        "schema_presence": sorted(set(schema_types)) or None,
        "open_graph": og or None,
        "twitter_cards": tw or None,
        "hreflang": hreflang or None,
        "content_hash": content_hash(visible),
        "links": links,
    }


def _empty(final_url: str) -> dict:
    return {
        "title": None, "title_length": 0, "meta_description": None,
        "meta_description_length": 0, "canonical": None, "robots_meta": None,
        "h1_count": 0, "h1_text": [], "word_count": 0, "language": None,
        "images_count": 0, "images_missing_alt": 0, "internal_links": 0,
        "external_links": 0, "is_noindex": False, "is_nofollow": False,
        "schema_presence": None, "open_graph": None, "twitter_cards": None,
        "hreflang": None, "content_hash": content_hash(""), "links": [],
    }
