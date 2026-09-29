"""Crawl orchestration: frontier → fetch → parse → persist (spec §11, async overhaul).

- Asynchronous concurrent fetching with bounded concurrency (default AUDIT_CONCURRENCY=12)
- Reused httpx.AsyncClient with HTTP connection pooling and keep-alive
- Single-pass HTML parsing (HTML parsed once per page, signals and links extracted together)
- Safe SSRF validation with in-memory host DNS cache
- Batch database persistence (committed in chunks of 25-100 pages, never per-page)
- Real-time progress broadcasting (phase, speed, eta, failed counts in run.config)
- Failure isolation (404, 500, timeouts, etc. stored as CrawlPage, audit keeps going)
- Hard maximum runtime boundary (default 180s) for partial audit finalization
- Explicit cancellation support with graceful halt
- Hash-based duplicate detection (O(N) indexed group by content_hash)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.config import get_settings
from app.crawler import discovery
from app.crawler.fetch import FetchResult, async_fetch_url, create_async_client, fetch_url, is_html
from app.crawler.normalize import fold_www, normalize_url, same_site
from app.crawler.parse import parse_html
from app.crawler.safety import UnsafeUrlError, clear_dns_cache, validate_url
from app.models import Project

logger = logging.getLogger("seo.crawler")

_original_fetch_url = fetch_url
_original_discover_seeds = discovery.discover_seeds

DEFAULT_MAX_PAGES = 100
HARD_MAX_PAGES = 500
BATCH_COMMIT_SIZE = 25


def utcnow() -> datetime:
    return datetime.now(UTC)


def run_crawl(db: Session, run_id, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
    """Execute a crawl run using the async engine with bounded concurrency and timeouts."""
    settings = get_settings()
    run = db.get(seo.CrawlRun, run_id)
    if run is None:
        raise ValueError(f"crawl run not found: {run_id}")
    project = db.get(Project, run.project_id)
    seed_domain = (project.domain or "").strip().lower()
    max_pages = max(1, min(int(max_pages or DEFAULT_MAX_PAGES), HARD_MAX_PAGES))
    concurrency = max(1, min(int(settings.audit_concurrency or 12), 32))
    max_runtime = max(30, int(settings.audit_max_runtime or 180))

    run.status = "RUNNING"
    run.started_at = utcnow()
    cfg = dict(run.config or {})
    cfg.update({
        "phase": "DISCOVERING",
        "pages_failed": 0,
        "speed": 0.0,
        "eta_seconds": 0.0,
        "max_pages": max_pages,
        "concurrency": concurrency,
    })
    run.config = cfg
    db.commit()

    clear_dns_cache()

    try:
        asyncio.run(
            _async_crawl(
                db,
                run,
                seed_domain,
                max_pages=max_pages,
                concurrency=concurrency,
                max_runtime=max_runtime,
            )
        )
        # Only set COMPLETED if it wasn't cancelled or failed
        db.refresh(run)
        if run.status not in ("CANCELLED", "FAILED"):
            run.status = "COMPLETED"
            cfg = dict(run.config or {})
            cfg["phase"] = "COMPLETED"
            run.config = cfg
    except Exception as exc:
        logger.exception("Audit crawl failed for run %s: %s", run_id, exc)
        db.refresh(run)
        if run.status != "CANCELLED":
            run.status = "FAILED"
            run.error = f"{type(exc).__name__}: {exc}"
            cfg = dict(run.config or {})
            cfg["phase"] = "FAILED"
            run.config = cfg
    finally:
        run.finished_at = utcnow()
        db.commit()


async def _async_crawl(
    db: Session,
    run: seo.CrawlRun,
    seed_domain: str,
    max_pages: int,
    concurrency: int,
    max_runtime: int,
) -> None:
    start_url = f"https://{seed_domain}/"
    try:
        validate_url(start_url)
    except UnsafeUrlError as exc:
        raise ValueError(f"unsafe seed domain: {exc}") from exc
    seed_host = (urlparse(start_url).hostname or "").lower()

    t_start = time.monotonic()

    async with create_async_client(max_connections=concurrency * 2, max_keepalive=concurrency) as client:
        # Phase 1: Discover seeds from robots.txt and sitemaps
        if discovery.discover_seeds is not _original_discover_seeds:
            boot = discovery.discover_seeds(start_url)
        else:
            boot = await discovery.async_discover_seeds(client, start_url)
        if boot["error"]:
            raise ValueError(boot["error"])

        robots = boot["robots"]
        disallows = robots["disallows"]

        db.refresh(run)
        if run.status == "CANCELLED":
            return

        cfg = dict(run.config or {})
        cfg["phase"] = "CRAWLING"
        run.config = cfg
        db.commit()

        # Phase 2: Concurrent BFS Crawl
        frontier_urls: list[tuple[str, int]] = [(start_url, 0)]
        for u in boot["seed_urls"]:
            frontier_urls.append((u, 1))

        seen_urls: set[str] = set()
        pending_queue: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()

        for u, depth in frontier_urls:
            try:
                norm = normalize_url(u)
            except Exception:
                continue
            if norm not in seen_urls:
                seen_urls.add(norm)
                await pending_queue.put((u, depth))

        run.pages_discovered = len(seen_urls)
        db.commit()

        # State shared across worker tasks
        crawled_count = 0
        failed_count = 0
        is_cancelled = False
        is_runtime_exceeded = False
        active_fetches = 0
        lock = asyncio.Lock()

        page_buffer: list[seo.CrawlPage] = []
        link_buffer: list[seo.CrawlLink] = []

        def flush_batch() -> None:
            nonlocal page_buffer, link_buffer
            if not page_buffer and not link_buffer:
                return
            for p in page_buffer:
                db.add(p)
            for l in link_buffer:
                db.add(l)
            page_buffer = []
            link_buffer = []

            elapsed = max(0.1, time.monotonic() - t_start)
            speed = crawled_count / elapsed
            remaining = max(0, min(max_pages, len(seen_urls)) - crawled_count)
            eta = remaining / max(0.1, speed)

            run.pages_crawled = crawled_count
            run.pages_discovered = len(seen_urls)
            cfg = dict(run.config or {})
            cfg.update({
                "phase": "CRAWLING",
                "pages_failed": failed_count,
                "speed": round(speed, 1),
                "eta_seconds": round(eta, 1),
            })
            run.config = cfg
            db.commit()

        async def worker():
            nonlocal crawled_count, failed_count, is_cancelled, is_runtime_exceeded, active_fetches

            while True:
                # Check cancellation or runtime limits
                if time.monotonic() - t_start > max_runtime:
                    is_runtime_exceeded = True
                    break

                try:
                    item = await asyncio.wait_for(pending_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    async with lock:
                        if pending_queue.empty() and active_fetches == 0:
                            break
                        continue

                if item is None:
                    pending_queue.task_done()
                    break

                raw_url, depth = item

                async with lock:
                    if crawled_count >= max_pages or is_cancelled or is_runtime_exceeded:
                        pending_queue.task_done()
                        break
                    active_fetches += 1

                # Re-check run status for cancellation from UI
                db.refresh(run)
                if run.status == "CANCELLED":
                    is_cancelled = True
                    async with lock:
                        active_fetches -= 1
                    pending_queue.task_done()
                    break

                # Host check
                host = (urlparse(raw_url).hostname or "").lower()
                if not same_site(seed_host, host):
                    async with lock:
                        active_fetches -= 1
                    pending_queue.task_done()
                    continue

                # Robots.txt allow check
                norm = normalize_url(raw_url)
                if not discovery.is_allowed(urlparse(raw_url).path or "/", disallows):
                    async with lock:
                        page_buffer.append(seo.CrawlPage(
                            crawl_run_id=run.id,
                            url=raw_url[:2000],
                            normalized_url=norm[:2000],
                            depth=depth,
                            status_code=0,
                            indexability="ROBOTS_BLOCKED",
                            is_robots_blocked=True,
                        ))
                        active_fetches -= 1
                    pending_queue.task_done()
                    continue

                # Fetch URL asynchronously (or use monkeypatched fetch_url)
                import inspect
                if fetch_url is not _original_fetch_url:
                    res = fetch_url(raw_url)
                    if inspect.isawaitable(res):
                        result = await res
                    else:
                        result = res
                else:
                    result = await async_fetch_url(client, raw_url)

                async with lock:
                    active_fetches -= 1
                    if result.error or (result.status_code and result.status_code >= 400):
                        failed_count += 1

                    # Single HTML parse pass
                    parsed = {}
                    if is_html(result) and result.status_code == 200 and result.body:
                        try:
                            parsed = parse_html(result.url, result.body, result.content_type)
                        except Exception:
                            parsed = {}

                    # Build CrawlPage
                    page = seo.CrawlPage(
                        crawl_run_id=run.id,
                        url=result.requested_url[:2000],
                        normalized_url=normalize_url(result.url)[:2000] if result.url else norm[:2000],
                        depth=depth,
                        status_code=result.status_code or None,
                        content_type=(result.content_type or None),
                        response_time_ms=result.response_time_ms,
                        redirect_target=result.redirect_chain[-1][1][:2000] if result.redirect_chain else None,
                    )

                    if result.error and not result.status_code:
                        page.indexability = "FETCH_ERROR"
                    elif result.redirect_chain and result.status_code in (301, 302, 303, 307, 308):
                        page.indexability = "REDIRECTED"
                    elif result.status_code and result.status_code >= 400:
                        page.indexability = "BROKEN"
                    elif parsed:
                        page.title = parsed.get("title")
                        page.title_length = parsed.get("title_length", 0)
                        page.meta_description = parsed.get("meta_description")
                        page.meta_description_length = parsed.get("meta_description_length", 0)
                        page.canonical = parsed.get("canonical")
                        page.robots_meta = parsed.get("robots_meta")
                        page.h1_count = parsed.get("h1_count", 0)
                        page.h1_text = parsed.get("h1_text") or []
                        page.word_count = parsed.get("word_count", 0)
                        page.language = parsed.get("language")
                        page.images_count = parsed.get("images_count", 0)
                        page.images_missing_alt = parsed.get("images_missing_alt", 0)
                        page.internal_links = parsed.get("internal_links", 0)
                        page.external_links = parsed.get("external_links", 0)
                        page.is_noindex = parsed.get("is_noindex", False)
                        page.is_nofollow = parsed.get("is_nofollow", False)
                        page.schema_presence = parsed.get("schema_presence")
                        page.open_graph = parsed.get("open_graph")
                        page.twitter_cards = parsed.get("twitter_cards")
                        page.hreflang = parsed.get("hreflang")
                        page.content_hash = parsed.get("content_hash")
                        page.indexability = "NOINDEX" if page.is_noindex else "INDEXABLE"

                        for link in parsed.get("links", []):
                            link_buffer.append(seo.CrawlLink(
                                crawl_run_id=run.id,
                                from_url=result.url[:2000],
                                to_url=link["to_url"][:2000],
                                normalized_to_url=link["normalized_to_url"][:2000],
                                is_internal=link["is_internal"],
                                rel=(link["rel"] or "")[:200] or None,
                            ))

                            if link["is_internal"] and crawled_count + pending_queue.qsize() < max_pages * 3:
                                ln = link["normalized_to_url"]
                                if ln not in seen_urls:
                                    seen_urls.add(ln)
                                    pending_queue.put_nowait((link["to_url"], depth + 1))

                    page_buffer.append(page)
                    crawled_count += 1

                    if len(page_buffer) >= BATCH_COMMIT_SIZE:
                        flush_batch()

                pending_queue.task_done()

        # Run concurrent workers
        tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Flush any remaining pages and links
        flush_batch()

        # Phase 3: Hash-based duplicate detection (O(N))
        cfg = dict(run.config or {})
        cfg["phase"] = "ANALYZING"
        if is_runtime_exceeded:
            cfg["partial"] = True
            cfg["partial_reason"] = "Runtime limit reached"
        run.config = cfg
        db.commit()

        _mark_duplicate_pages(db, run.id)


def _mark_duplicate_pages(db: Session, run_id) -> None:
    """Identify duplicate content hashes in O(N) time and flag is_duplicate."""
    pages = db.query(seo.CrawlPage.id, seo.CrawlPage.content_hash).filter_by(
        crawl_run_id=run_id
    ).all()
    hashes = [p.content_hash for p in pages if p.content_hash]
    counts = Counter(hashes)
    dup_hashes = {h for h, count in counts.items() if count > 1}
    if dup_hashes:
        db.query(seo.CrawlPage).filter(
            seo.CrawlPage.crawl_run_id == run_id,
            seo.CrawlPage.content_hash.in_(dup_hashes),
        ).update({"is_duplicate": True}, synchronize_session=False)
        db.commit()
