"""Incremental fills cache: data/discovery.db, per wallet.

Only fetches fills since the last cached time for that wallet (the
`fills_cursor` table). A run with a wider window than a previous run just
reads more out of the local cache for the already-covered range; it never
re-fetches a timestamp already on disk.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from contracts.venue import Venue

from . import db

DAY_MS = 86_400_000
MAX_PAGES = 20   # HL caps userFillsByTime at ~2000 rows/call; page forward on a full page


def sync_fills(conn: sqlite3.Connection, venue: Venue, wallet: str, window_days: int,
               now_ms: int) -> List[Dict[str, Any]]:
    """Ensure the cache holds every fill for `wallet` from (now_ms - window_days)
    to now_ms, fetching only the gap since the last sync, then return the
    full cached window."""
    window_start_ms = now_ms - window_days * DAY_MS
    cursor = db.get_fills_cursor(conn, wallet)
    fetch_start = max(cursor + 1, window_start_ms) if cursor is not None else window_start_ms

    if fetch_start <= now_ms:
        start = fetch_start
        for _ in range(MAX_PAGES):
            batch = venue.fills(wallet, start, now_ms)
            if not batch:
                break
            db.insert_fills(conn, wallet, batch)
            max_t = max(int(f["time_ms"]) for f in batch)
            if len(batch) < 1900 or max_t <= start:
                break
            start = max_t + 1
        db.set_fills_cursor(conn, wallet, now_ms)

    return db.get_cached_fills(conn, wallet, window_start_ms, now_ms)
