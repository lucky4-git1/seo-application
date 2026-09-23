"""HTTP fetching with safety + limits (spec §13).

- SSRF validation before connect AND on every redirect hop
- redirect loop handled manually (follow_redirects=False)
- timeout, max response size (streamed, abort early), redirect cap
- content-type + compression handled by httpx; HTML sniffed by type
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.crawler.safety import UnsafeUrlError, validate_url

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 15.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "SEOBot/0.1 (+https://example.com/bot; crawl for site owner)"


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    requested_url: str
    status_code: int
    headers: dict = field(default_factory=dict)
    content_type: str = ""
    body: bytes = b""
    response_time_ms: int = 0
    redirect_chain: list = field(default_factory=list)  # [(from, to, status)]
    error: str | None = None
    truncated: bool = False


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                              write=READ_TIMEOUT, pool=READ_TIMEOUT),
        follow_redirects=False,
        max_redirects=0,
    )


def fetch_url(url: str, *, max_redirects: int = MAX_REDIRECTS) -> FetchResult:
    """Fetch one URL, manually following same-validated redirects."""
    validate_url(url)
    chain: list = []
    current = url
    started = time.perf_counter()
    try:
        with _client() as client:
            for _ in range(max_redirects + 1):
                validate_url(current)
                try:
                    with client.stream("GET", current) as resp:
                        status = resp.status_code
                        if status in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location", "")
                            nxt = httpx.URL(current).join(location) if location else ""
                            chain.append((current, str(nxt), status))
                            if not nxt or not str(nxt).strip():
                                return FetchResult(
                                    url=current, requested_url=url, status_code=status,
                                    response_time_ms=_elapsed(started),
                                    redirect_chain=chain,
                                    error="redirect without location")
                            current = str(nxt)
                            continue
                        return _read_body(resp, url, current, chain, started)
                except (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout) as exc:
                    return FetchResult(url=current, requested_url=url, status_code=0,
                                       response_time_ms=_elapsed(started),
                                       error=f"network error: {type(exc).__name__}")
            return FetchResult(url=current, requested_url=url, status_code=0,
                               response_time_ms=_elapsed(started),
                               redirect_chain=chain, error="too many redirects")
    except UnsafeUrlError as exc:
        return FetchResult(url=current, requested_url=url, status_code=0,
                           response_time_ms=_elapsed(started),
                           redirect_chain=chain, error=f"blocked: {exc}")


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _read_body(resp, requested_url, current, chain, started) -> FetchResult:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    chunks: list[bytes] = []
    total = 0
    truncated = False
    try:
        for chunk in resp.iter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                truncated = True
                break
            chunks.append(chunk)
    except (httpx.ReadTimeout, httpx.DecodingError, httpx.StreamClosed,
            httpx.StreamConsumed) as exc:
        return FetchResult(url=current, requested_url=requested_url,
                           status_code=resp.status_code, content_type=ctype,
                           response_time_ms=int((time.perf_counter() - started) * 1000),
                           redirect_chain=chain, error=f"body error: {type(exc).__name__}")
    return FetchResult(
        url=current, requested_url=requested_url, status_code=resp.status_code,
        headers=dict(resp.headers), content_type=ctype, body=b"".join(chunks),
        response_time_ms=int((time.perf_counter() - started) * 1000),
        redirect_chain=chain, truncated=truncated,
    )


def is_html(result: FetchResult) -> bool:
    return not result.content_type or "html" in result.content_type
