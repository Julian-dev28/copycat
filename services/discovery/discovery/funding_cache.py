"""Incremental funding cache: data/discovery.db, per wallet. Mirrors
fills_cache.py's coverage-tracked sync; see that module's docstring for the
general shape (one contiguous `[first_ms, last_ms]` range known fully on
disk, a sync fetches only what is missing).

`venue.funding` is optional (contracts.venue.Venue docstring): a Venue that
doesn't implement it (older fakes, CacheOnlyVenue in what-if sims) is not an
error -- the sync is a no-op and callers net 0 funding, the same as before
this cache existed. A Venue that HAS it but whose read fails (HL down, a
429) still raises FundingFetchError: once we know funding exists for this
account, silently treating a failed fetch as "no funding" would understate
every round trip's net PnL.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts.venue import Venue

from . import db

DAY_MS = 86_400_000


class FundingFetchError(RuntimeError):
    pass


def supports_funding(venue: Any) -> bool:
    return callable(getattr(venue, "funding", None))


def _fetch(venue: Venue, wallet: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    rows = venue.funding(wallet, start_ms, end_ms)  # type: ignore[attr-defined]
    if rows is None:
        raise FundingFetchError(f"funding read failed for {wallet} [{start_ms}, {end_ms}]")
    return rows


def sync_funding(conn: Any, venue: Venue, wallet: str, window_days: int, now_ms: int,
                 fresh_s: float = 0.0) -> List[Dict[str, Any]]:
    """Make the cache hold every funding settlement for `wallet` in
    [now_ms - window_days, now_ms] (fetching only what is missing), then
    return that window from the cache. [] when the venue has no `funding`
    method at all (never raises for that -- it is an optional read)."""
    if not supports_funding(venue):
        return []
    ws = now_ms - window_days * DAY_MS
    cov = db.get_funding_coverage(conn, wallet)

    if cov is None:
        db.insert_funding(conn, wallet, _fetch(venue, wallet, ws, now_ms))
        db.set_funding_coverage(conn, wallet, ws, now_ms, now_ms)
        return db.get_cached_funding(conn, wallet, ws, now_ms)

    first, last, fetched = cov["first_ms"], cov["last_ms"], cov["fetched_ms"]
    if ws < first:
        db.insert_funding(conn, wallet, _fetch(venue, wallet, ws, first - 1))
        first = ws
        db.set_funding_coverage(conn, wallet, first, last, fetched)
    fresh = fresh_s > 0 and (now_ms - fetched) <= fresh_s * 1000
    if last < now_ms and not fresh:
        db.insert_funding(conn, wallet, _fetch(venue, wallet, last + 1, now_ms))
        last = now_ms
        db.set_funding_coverage(conn, wallet, first, last, now_ms)
    return db.get_cached_funding(conn, wallet, ws, min(now_ms, last))


def cached_window(conn: Any, wallet: str, window_days: int, now_ms: int) -> List[Dict[str, Any]]:
    """Read whatever funding is already cached for `wallet` in the last
    `window_days`, with no HL call and no coverage write. Used on a stage-B
    pass that skips the funding sync (indexing tightening: funding moves to
    a slower cadence, `scout.config.FULL_REFRESH_EVERY_S`): round-trip
    netting uses the last successfully fetched funding, up to that cadence
    stale, instead of paying a userFunding page every hourly pass. []
    when nothing has ever been cached for this wallet -- same empty-list
    shape `sync_funding` returns for "no funding events", not an error."""
    cov = db.get_funding_coverage(conn, wallet)
    if cov is None:
        return []
    ws = now_ms - window_days * DAY_MS
    return db.get_cached_funding(conn, wallet, ws, min(now_ms, cov["last_ms"]))
