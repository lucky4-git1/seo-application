"""SSRF protection for the crawler (Step 3, spec §13 — mandatory).

Every URL is validated *before* any byte is fetched, and every redirect hop
is re-validated. Defense layers:

1. scheme allowlist (http/https only), no userinfo, host required
2. hostname blocklist (localhost variants, single-dot edge cases handled by 3)
3. DNS resolution of the *actual* target host — every resolved IP must be
   globally routable (rejects private/loopback/link-local/reserved/multicast,
   which covers 127.0.0.0/8, 10/8, 172.16/12, 192.168/16, 169.254/16 incl.
   cloud metadata 169.254.169.254, ::1, fc00::/7, fe80::/10, 0.0.0.0)
4. caller-enforced limits live in fetch.py (timeout, size, redirects);
   this module exposes the pure checks so they are unit-testable.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LENGTH = 2000

# Hostnames that can never be crawled, even if DNS would resolve weirdly.
BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
}


class UnsafeUrlError(ValueError):
    """Raised when a URL fails SSRF validation."""


def _parse(url: str):
    try:
        return urlparse(url)
    except Exception as exc:
        raise UnsafeUrlError(f"unparseable URL: {exc}") from exc


def validate_url(url: str) -> str:
    """Validate a candidate crawl URL. Returns the URL unchanged if safe."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeUrlError("empty or over-long URL")
    parts = _parse(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"disallowed scheme: {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeUrlError("userinfo in URL is not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeUrlError("URL has no host")
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafeUrlError(f"blocked host: {host}")
    try:
        is_literal_ip = ipaddress.ip_address(host) is not None
    except ValueError:
        is_literal_ip = False
    if is_literal_ip:
        # Literal IP in the URL — check it directly, no DNS needed.
        _reject_non_global(host)
        return url
    _check_dns(host)
    return url


def _reject_non_global(host_or_ip: str) -> None:
    try:
        ip = ipaddress.ip_address(host_or_ip)
    except ValueError as exc:
        raise UnsafeUrlError(f"invalid IP literal: {host_or_ip}") from exc
    # is_global is False for private, loopback, link-local, reserved,
    # multicast, unspecified — exactly the set we must never fetch.
    if not ip.is_global:
        raise UnsafeUrlError(f"non-routable IP: {host_or_ip}")


_DNS_CACHE: dict[str, bool] = {}


def clear_dns_cache() -> None:
    _DNS_CACHE.clear()


def _check_dns(host: str) -> None:
    if host in _DNS_CACHE:
        return
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"DNS resolution failed for {host}: {exc}") from exc
    if not infos:
        raise UnsafeUrlError(f"DNS returned no addresses for {host}")
    for info in infos:
        addr = info[4][0]
        _reject_non_global(addr)
    _DNS_CACHE[host] = True
