"""GSC synchronization: Search Analytics → gsc_query_data/gsc_page_data.

Incremental by date range, idempotent by grain unique constraints (re-syncs
update changed rows). Portable upsert logic (no PG-only SQL) so tests run on
SQLite.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.providers import crypto
from app.providers.google import SearchConsoleClient, utcnow


def utcnow_local() -> datetime:
    return datetime.now(UTC)


def daterange(days: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=max(1, min(days, 365)))
    return start.isoformat(), end.isoformat()


def client_for(db: Session, conn: seo.GscConnection) -> SearchConsoleClient:
    access = crypto.decrypt_credentials(conn.access_token_enc)["token"]
    refresh = crypto.decrypt_credentials(conn.refresh_token_enc)["token"]

    def on_refresh(data: dict) -> None:
        conn.access_token_enc = crypto.encrypt_credentials({"token": data["access_token"]})
        conn.expires_at = data["expires_at"]
        db.commit()

    return SearchConsoleClient(access, conn.expires_at, refresh, on_refresh)


def _upsert_query(db: Session, prop_id: uuid.UUID, day: date, query: str,
                  country: str, device: str, clicks: int, impressions: int,
                  ctr: float, position: float) -> str:
    row = (db.query(seo.GscQueryData)
           .filter_by(property_id=prop_id, date=day, query=query,
                      country=country, device=device).first())
    if row is None:
        db.add(seo.GscQueryData(property_id=prop_id, date=day, query=query,
                                country=country, device=device, clicks=clicks,
                                impressions=impressions, ctr=ctr, position=position))
        return "inserted"
    row.clicks, row.impressions, row.ctr, row.position = clicks, impressions, ctr, position
    return "updated"


def _upsert_page(db: Session, prop_id: uuid.UUID, day: date, page: str,
                 country: str, device: str, clicks: int, impressions: int,
                 ctr: float, position: float) -> str:
    row = (db.query(seo.GscPageData)
           .filter_by(property_id=prop_id, date=day, page=page,
                      country=country, device=device).first())
    if row is None:
        db.add(seo.GscPageData(property_id=prop_id, date=day, page=page,
                               country=country, device=device, clicks=clicks,
                               impressions=impressions, ctr=ctr, position=position))
        return "inserted"
    row.clicks, row.impressions, row.ctr, row.position = clicks, impressions, ctr, position
    return "updated"


def _pull(client: SearchConsoleClient, site_url: str, start: str, end: str,
          dimensions: list[str], max_pages: int = 5) -> list[dict]:
    out: list[dict] = []
    start_row = 0
    for _ in range(max_pages):
        rows = client.query_analytics(site_url, start, end, dimensions,
                                      row_limit=25000, start_row=start_row)
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 25000:
            break
        start_row += 25000
    return out


def sync_property(db: Session, prop: seo.GscProperty, client: SearchConsoleClient,
                  days: int = 90, max_pages: int = 5) -> dict:
    """Sync one property. Returns counts. Raises ProviderError on failure."""
    start, end = daterange(days)
    stats = {"queries_inserted": 0, "queries_updated": 0,
             "pages_inserted": 0, "pages_updated": 0}

    for row in _pull(client, prop.site_url, start, end,
                     ["date", "query", "country", "device"], max_pages):
        keys = row.get("keys", ["", "", "all", "all"])
        day = date.fromisoformat(keys[0])
        action = _upsert_query(
            db, prop.id, day, keys[1], (keys[2] or "all").lower(),
            (keys[3] or "all").upper(), int(row.get("clicks", 0)),
            int(row.get("impressions", 0)), float(row.get("ctr", 0)),
            float(row.get("position", 0)))
        stats["queries_inserted" if action == "inserted" else "queries_updated"] += 1

    for row in _pull(client, prop.site_url, start, end,
                     ["date", "page", "country", "device"], max_pages):
        keys = row.get("keys", ["", "", "all", "all"])
        day = date.fromisoformat(keys[0])
        action = _upsert_page(
            db, prop.id, day, keys[1], (keys[2] or "all").lower(),
            (keys[3] or "all").upper(), int(row.get("clicks", 0)),
            int(row.get("impressions", 0)), float(row.get("ctr", 0)),
            float(row.get("position", 0)))
        stats["pages_inserted" if action == "inserted" else "pages_updated"] += 1

    prop.last_synced_at = utcnow()
    db.commit()
    return stats
