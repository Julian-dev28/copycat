"""Incremental fills cache: data/discovery.db, per wallet.

`fills_coverage` holds the one contiguous range [first_ms, last_ms] that is
known to be fully on disk for a wallet. A sync for window [ws, now] fetches
only what lies outside it: a backfill [ws, first_ms - 1] when the window
widened, and a tail [last_ms + 1, now]. Coverage only moves after a
successful fetch; a failed read (venue returns None, e.g. an HL 429) raises
FillsFetchError and leaves the cache exactly as it was, so the next run
retries instead of silently treating the wallet as flat.

Freshness: when the coverage was fetched less than `fresh_s` ago, the tail
fetch is skipped (the window then ends at last_ms, at most fresh_s stale).
That is what makes a warm re-run cheap: every userFillsByTime call costs a
base weight of 20 plus 1 per 20 fills returned (charged after the response).

Aggregation: HL's userFillsByTime takes `aggregateByTime`, which merges the
partial fills of one crossing order into one fill. Measured 2026-10-03 on
0x350e33a7: one 2000-fill page covered 0.9h raw vs 107h aggregated (~120x
fewer pages). contracts.venue.Venue.fills takes `aggregate_by_time`; it is
passed whenever the venue accepts it (fakes in tests may not).
"""
from __future__ import annotations

import inspect
import sqlite3
from typing import Any, Dict, List, Optional

from contracts.venue import Venue

from . import db

DAY_MS = 86_400_000


class FillsFetchError(RuntimeError):
    pass


def _supports_aggregate(venue: Venue) -> bool:
    try:
        return "aggregate_by_time" in inspect.signature(venue.fills).parameters
    except (TypeError, ValueError):
        return False


def _fetch(venue: Venue, wallet: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    if _supports_aggregate(venue):
        rows = venue.fills(wallet, start_ms, end_ms, aggregate_by_time=True)  # type: ignore[call-arg]
    else:
        rows = venue.fills(wallet, start_ms, end_ms)
    if rows is None:
        raise FillsFetchError(f"fills read failed for {wallet} [{start_ms}, {end_ms}]")
    return rows


def sync_fills(conn: sqlite3.Connection, venue: Venue, wallet: str, window_days: int,
               now_ms: int, fresh_s: float = 0.0) -> List[Dict[str, Any]]:
    """Make the cache hold every fill for `wallet` in [now_ms - window_days, now_ms]
    (fetching only what is missing), then return that window from the cache."""
    ws = now_ms - window_days * DAY_MS
    cov = db.get_fills_coverage(conn, wallet)

    if cov is None:
        db.insert_fills(conn, wallet, _fetch(venue, wallet, ws, now_ms))
        db.set_fills_coverage(conn, wallet, ws, now_ms, now_ms)
        return db.get_cached_fills(conn, wallet, ws, now_ms)

    first, last, fetched = cov["first_ms"], cov["last_ms"], cov["fetched_ms"]
    if ws < first:
        db.insert_fills(conn, wallet, _fetch(venue, wallet, ws, first - 1))
        first = ws
        db.set_fills_coverage(conn, wallet, first, last, fetched)
    fresh = fresh_s > 0 and (now_ms - fetched) <= fresh_s * 1000
    if last < now_ms and not fresh:
        db.insert_fills(conn, wallet, _fetch(venue, wallet, last + 1, now_ms))
        last = now_ms
        db.set_fills_coverage(conn, wallet, first, last, now_ms)
    return db.get_cached_fills(conn, wallet, ws, min(now_ms, last))


def coverage_end(conn: sqlite3.Connection, wallet: str) -> Optional[int]:
    cov = db.get_fills_coverage(conn, wallet)
    return cov["last_ms"] if cov else None
