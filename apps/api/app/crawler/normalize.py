"""URL normalization + canonicalization for crawl frontier and storage.

- scheme/host lowercased, default ports stripped
- fragments dropped, tracking params (utm_*, gclid, fbclid, ...) dropped
- trailing slash: root keeps "/", non-root trailing slash preserved as-is
  (changing it merges distinct resources on some servers — dedup only on
  exact normalized form + www/alias folding done by the caller)
- www folding helper for same-site checks
- original URL is ALWAYS preserved alongside normalized form in storage
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "mc_cid",
    "mc_eid", "igshid", "ref", "ref_src",
}


def normalize_url(url: str) -> str:
    parts = urlparse(url.strip())
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k.lower() not in TRACKING_PARAMS],
        doseq=True,
    )
    path = parts.path or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))


def fold_www(host: str) -> str:
    """Strip one leading www. so apex/www compare equal."""
    host = host.lower()
    return host.removeprefix("www.")


def same_site(seed_host: str, link_host: str) -> bool:
    """True when link_host belongs to the same site as seed_host.

    Same registrable boundaries without external deps: exact match after
    www-folding. Subdomains are treated as separate sites (documented).
    """
    return fold_www(seed_host) == fold_www(link_host) and bool(fold_www(seed_host))


def is_http_url(url: str) -> bool:
    try:
        return urlparse(url).scheme in ("http", "https")
    except Exception:
        return False
