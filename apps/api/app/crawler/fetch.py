"""HTTP fetching with safety + limits (spec §13, async overhaul).

- SSRF validation before connect AND on every redirect hop
- Redirect loop handled manually (follow_redirects=False)
- Bounded timeouts (connect 5s, read 15s, total 20s)
- Max response size (streamed, abort early), redirect cap
- Connection pooling and keep-alive reuse via httpx.AsyncClient
- Transient retry policy (max 2 retries, exponential backoff, respects Retry-After)
- Synchronous fetch_url preserved for backwards compatibility and test harnesses
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from app.crawler.safety import UnsafeUrlError, validate_url

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 15.0
TOTAL_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_RETRIES = 2
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
    retries: int = 0


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                              write=READ_TIMEOUT, pool=READ_TIMEOUT),
        follow_redirects=False,
        max_redirects=0,
    )


def create_async_client(max_connections: int = 50, max_keepalive: int = 20) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive,
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(
        TOTAL_TIMEOUT,
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=READ_TIMEOUT,
        pool=READ_TIMEOUT,
    )
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
    )


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _is_transient_status(code: int) -> bool:
    return code in (429, 502, 503, 504)


async def async_fetch_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = MAX_REDIRECTS,
    max_retries: int = MAX_RETRIES,
) -> FetchResult:
    """Asynchronously fetch one URL with SSRF checks, redirect handling, and bounded retries."""
    try:
        validate_url(url)
    except UnsafeUrlError as exc:
        return FetchResult(url=url, requested_url=url, status_code=0, error=f"blocked: {exc}")

    started = time.perf_counter()
    chain: list = []
    current = url
    attempt = 0

    while True:
        try:
            # Follow redirects manually with SSRF revalidation
            for hop in range(max_redirects + 1):
                validate_url(current)
                try:
                    async with client.stream("GET", current) as resp:
                        status = resp.status_code
                        # Handle redirect status codes
                        if status in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location", "")
                            nxt = httpx.URL(current).join(location) if location else ""
                            chain.append((current, str(nxt), status))
                            if not nxt or not str(nxt).strip():
                                return FetchResult(
                                    url=current, requested_url=url, status_code=status,
                                    headers=dict(resp.headers),
                                    response_time_ms=_elapsed(started),
                                    redirect_chain=chain,
                                    error="redirect without location",
                                    retries=attempt,
                                )
                            current = str(nxt)
                            continue

                        # Check for transient retryable HTTP errors (e.g. 502, 503, 504, 429)
                        if _is_transient_status(status) and attempt < max_retries:
                            retry_after = 0.5 * (2 ** attempt)
                            raw_ra = resp.headers.get("Retry-After")
                            if raw_ra and raw_ra.isdigit():
                                retry_after = min(float(raw_ra), 5.0)
                            attempt += 1
                            await asyncio.sleep(retry_after)
                            # Retry from current URL
                            break

                        # Read stream body
                        return await _async_read_body(resp, url, current, chain, started, attempt)

                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                        httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                    if attempt < max_retries:
                        attempt += 1
                        await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                        break
                    return FetchResult(
                        url=current, requested_url=url, status_code=0,
                        response_time_ms=_elapsed(started),
                        redirect_chain=chain,
                        error=f"network error: {type(exc).__name__}",
                        retries=attempt,
                    )

            else:
                return FetchResult(
                    url=current, requested_url=url, status_code=0,
                    response_time_ms=_elapsed(started),
                    redirect_chain=chain, error="too many redirects",
                    retries=attempt,
                )

        except UnsafeUrlError as exc:
            return FetchResult(
                url=current, requested_url=url, status_code=0,
                response_time_ms=_elapsed(started),
                redirect_chain=chain, error=f"blocked: {exc}",
                retries=attempt,
            )


async def _async_read_body(resp, requested_url: str, current: str, chain: list, started: float, attempt: int) -> FetchResult:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    chunks: list[bytes] = []
    total = 0
    truncated = False
    try:
        async for chunk in resp.aiter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                truncated = True
                break
            chunks.append(chunk)
    except (httpx.ReadTimeout, httpx.DecodingError, httpx.StreamClosed,
            httpx.StreamConsumed) as exc:
        return FetchResult(
            url=current, requested_url=requested_url, status_code=resp.status_code,
            headers=dict(resp.headers), content_type=ctype,
            response_time_ms=_elapsed(started),
            redirect_chain=chain, error=f"body error: {type(exc).__name__}",
            retries=attempt,
        )
    return FetchResult(
        url=current, requested_url=requested_url, status_code=resp.status_code,
        headers=dict(resp.headers), content_type=ctype, body=b"".join(chunks),
        response_time_ms=_elapsed(started),
        redirect_chain=chain, truncated=truncated, retries=attempt,
    )


def fetch_url(url: str, *, max_redirects: int = MAX_REDIRECTS) -> FetchResult:
    """Fetch one URL, manually following same-validated redirects (sync fallback)."""
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
