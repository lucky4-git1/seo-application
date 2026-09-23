"""Crawl orchestration: frontier → fetch → parse → persist (spec §11).

Runs inside a Celery worker (see app/tasks.py). Synchronous, polite,
bounded:

- seeds: homepage first, then sitemap URLs, then discovered links (BFS)
- same-site only (www-folded), robots.txt honored, crawl-delay honored
- per-domain politeness delay, page cap (default 200, hard max 500)
- every fetched URL persisted as CrawlPage (incl. errors/redirects)
- links persisted as CrawlLink (internal + external targets)
- run counters updated incrementally so the UI progress bar is real
"""
from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.crawler import discovery
from app.crawler.fetch import FetchResult, fetch_url, is_html
from app.crawler.normalize import normalize_url, same_site
from app.crawler.parse import parse_html
from app.crawler.safety import UnsafeUrlError, validate_url
from app.models import Project

DEFAULT_MAX_PAGES = 200
HARD_MAX_PAGES = 500
POLITENESS_DELAY = 0.25
PROGRESS_EVERY = 5


def utcnow() -> datetime:
    return datetime.now(UTC)


def run_crawl(db: Session, run_id, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
    """Execute a crawl run to completion (or failure). Commits incrementally."""
    run = db.get(seo.CrawlRun, run_id)
    if run is None:
        raise ValueError(f"crawl run not found: {run_id}")
    project = db.get(Project, run.project_id)
    seed_domain = (project.domain or "").strip().lower()
    max_pages = max(1, min(int(max_pages or DEFAULT_MAX_PAGES), HARD_MAX_PAGES))

    run.status = "RUNNING"
    run.started_at = utcnow()
    db.commit()

    try:
        _crawl(db, run, seed_domain, max_pages)
        run.status = "COMPLETED"
    except Exception as exc:
        run.status = "FAILED"
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.finished_at = utcnow()
        db.commit()


def _crawl(db: Session, run: seo.CrawlRun, seed_domain: str, max_pages: int) -> None:
    start_url = f"https://{seed_domain}/"
    try:
        validate_url(start_url)
    except UnsafeUrlError as exc:
        raise ValueError(f"unsafe seed domain: {exc}") from exc
    seed_host = (urlparse(start_url).hostname or "").lower()

    boot = discovery.discover_seeds(start_url)
    if boot["error"]:
        raise ValueError(boot["error"])
    robots = boot["robots"]
    delay = max(POLITENESS_DELAY, robots["crawl_delay"] or 0.0)

    frontier: deque[tuple[str, int]] = deque()
    frontier.append((start_url, 0))
    for u in boot["seed_urls"]:
        frontier.append((u, 1))
    seen: set[str] = set()
    crawled = 0
    last_fetch = 0.0

    while frontier and crawled < max_pages:
        raw_url, depth = frontier.popleft()
        try:
            norm = normalize_url(raw_url)
        except Exception:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        run.pages_discovered = len(seen)
        if crawled % PROGRESS_EVERY == 0:
            db.commit()

        host = (urlparse(raw_url).hostname or "").lower()
        if not same_site(seed_host, host):
            continue
        if not discovery.is_allowed(urlparse(raw_url).path or "/", robots["disallows"]):
            _store_blocked(db, run, raw_url, norm)
            continue

        wait = delay - (time.monotonic() - last_fetch)
        if wait > 0:
            time.sleep(wait)
        result = fetch_url(raw_url)
        last_fetch = time.monotonic()
        _store_page(db, run, result, norm, depth, seed_host, robots["disallows"])
        crawled += 1
        run.pages_crawled = crawled
        db.commit()

        if is_html(result) and result.status_code == 200 and result.body:
            try:
                parsed = parse_html(result.url, result.body, result.content_type)
            except Exception:
                continue
            for link in parsed.get("links", []):
                if not link["is_internal"]:
                    continue
                try:
                    ln = normalize_url(link["to_url"])
                except Exception:
                    continue
                if ln not in seen:
                    frontier.append((link["to_url"], depth + 1))


def _store_blocked(db: Session, run: seo.CrawlRun, raw_url: str, norm: str) -> None:
    db.add(seo.CrawlPage(
        crawl_run_id=run.id, url=raw_url[:2000], normalized_url=norm[:2000],
        status_code=0, indexability="ROBOTS_BLOCKED", is_robots_blocked=True))
    db.commit()


def _store_page(db: Session, run: seo.CrawlRun, result: FetchResult,
                norm: str, depth: int, seed_host: str, disallows: list) -> None:
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
    elif is_html(result) and result.status_code == 200 and result.body:
        try:
            parsed = parse_html(result.url, result.body, result.content_type)
        except Exception:
            parsed = {}
        if parsed:
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
                db.add(seo.CrawlLink(
                    crawl_run_id=run.id,
                    from_url=result.url[:2000],
                    to_url=link["to_url"][:2000],
                    normalized_to_url=link["normalized_to_url"][:2000],
                    is_internal=link["is_internal"],
                    rel=(link["rel"] or "")[:200] or None,
                ))
    db.add(page)
