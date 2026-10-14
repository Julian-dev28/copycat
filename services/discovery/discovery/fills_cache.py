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

Per-pass page cap (indexing tightening, 2026-10): `max_pages` bounds the real
userFillsByTime pages ONE sync_fills call may spend, on its first-ever sync
or its tail (never the rare widen-gap case -- see `_fetch_capped`). Default
(None) is the original, uncapped, single-call behavior: every existing
caller and test keeps that unless it opts in.
"""
from __future__ import annotations

import inspect
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from contracts.venue import Venue

from . import db

DAY_MS = 86_400_000
FILLS_PAGE_ROWS = 2000    # mirrors hl.venue.fills' real page size / scout.config.W_FILLS_PAGE accounting


class FillsFetchError(RuntimeError):
    pass


def _supports_aggregate(venue: Venue) -> bool:
    try:
        return "aggregate_by_time" in inspect.signature(venue.fills).parameters
    except (TypeError, ValueError):
        return False


def _supports_max_pages(venue: Venue) -> bool:
    try:
        return "max_pages" in inspect.signature(venue.fills).parameters
    except (TypeError, ValueError):
        return False


def _fetch(venue: Venue, wallet: str, start_ms: int, end_ms: int, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
    kwargs: Dict[str, Any] = {}
    if _supports_aggregate(venue):
        kwargs["aggregate_by_time"] = True
    if max_pages is not None and _supports_max_pages(venue):
        kwargs["max_pages"] = max_pages
    rows = venue.fills(wallet, start_ms, end_ms, **kwargs)  # type: ignore[call-arg]
    if rows is None:
        raise FillsFetchError(f"fills read failed for {wallet} [{start_ms}, {end_ms}]")
    return rows


def _fetch_capped(venue: Venue, wallet: str, lo_ms: int, hi_ms: int,
                  max_pages: Optional[int]) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Fetch [lo_ms, hi_ms] inclusive (oldest first, as HL returns them).

    With `max_pages=None`: one call, the original behavior exactly (every
    existing test's call shape). With `max_pages` set: still one call, but
    the venue itself is asked to stop after `max_pages` real pages (hl.venue
    honors this; a fake that doesn't just gets the full answer, same as
    before). Whether that cap actually bit is inferred the same safe-direction
    way M.fills_truncated already infers HL's OWN 10k-row cap: a result at or
    above `max_pages` worth of rows means "assume more exists past here" --
    the cost of a false positive is a few already-covered rows re-fetched
    next pass, never a silent gap. Returns (rows, reached_ms, truncated):
    reached_ms is how far [lo_ms, hi_ms] is actually covered now."""
    rows = _fetch(venue, wallet, lo_ms, hi_ms, max_pages=max_pages)
    if max_pages is None:
        return rows, hi_ms, False
    pages = max(1, math.ceil(len(rows) / FILLS_PAGE_ROWS)) if rows else 0
    if pages < max_pages:
        return rows, hi_ms, False
    reached = max((int(f["time_ms"]) for f in rows), default=lo_ms - 1)
    return rows, reached, True


def sync_fills(conn: sqlite3.Connection, venue: Venue, wallet: str, window_days: int,
               now_ms: int, fresh_s: float = 0.0, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
    """Make the cache hold every fill for `wallet` in [now_ms - window_days, now_ms]
    (fetching only what is missing), then return that window from the cache.

    `max_pages`, when set, bounds the first-ever sync and the tail (both
    walk forward, oldest-first, so a capped result is honestly short on the
    RECENT edge: coverage stays contiguous, `last_ms` just lags `now_ms`
    until a later pass catches it up -- see `fills_cache.is_lagging`). The
    widen-gap branch (`ws < first`, dead in steady state: ws only moves
    forward) stays uncapped -- capping it would leave a hole in the MIDDLE
    of the covered range instead of a lag at an edge, breaking the one-
    contiguous-range invariant this whole cache relies on."""
    ws = now_ms - window_days * DAY_MS
    cov = db.get_fills_coverage(conn, wallet)

    if cov is None:
        rows, reached, _truncated = _fetch_capped(venue, wallet, ws, now_ms, max_pages)
        db.insert_fills(conn, wallet, rows)
        db.set_fills_coverage(conn, wallet, ws, reached, now_ms)
        db.mark_liq_backfilled(conn, wallet)   # a first-ever sync already carries real liquidation flags
        return db.get_cached_fills(conn, wallet, ws, reached)

    first, last, fetched = cov["first_ms"], cov["last_ms"], cov["fetched_ms"]
    if ws < first:
        db.insert_fills(conn, wallet, _fetch(venue, wallet, ws, first - 1))   # uncapped: see docstring
        first = ws
        db.set_fills_coverage(conn, wallet, first, last, fetched)
    fresh = fresh_s > 0 and (now_ms - fetched) <= fresh_s * 1000
    if last < now_ms and not fresh:
        rows, reached, truncated = _fetch_capped(venue, wallet, last + 1, now_ms, max_pages)
        db.insert_fills(conn, wallet, rows)
        last = reached
        db.set_fills_coverage(conn, wallet, first, last, fetched if truncated else now_ms)
    return db.get_cached_fills(conn, wallet, ws, min(now_ms, last))


def coverage_end(conn: sqlite3.Connection, wallet: str) -> Optional[int]:
    cov = db.get_fills_coverage(conn, wallet)
    return cov["last_ms"] if cov else None


def newest_fill_ms(conn: sqlite3.Connection, wallet: str) -> Optional[int]:
    """The newest cached fill's time_ms, or None if nothing is cached yet.
    Used to tell "a new fill actually landed" apart from "the tail sync's
    bookkeeping just advanced `last_ms` to now with nothing new in it" --
    the latter happens on every pass that isn't fresh, trade or no trade."""
    return db.newest_fill_ms(conn, wallet)


LAG_FLAG_MS = 3 * 60 * 60 * 1000   # 3h: well past one normal pass's freshness skip (CACHE_FRESH_S, 15 min)


def is_lagging(conn: sqlite3.Connection, wallet: str, now_ms: int, slack_ms: int = LAG_FLAG_MS) -> bool:
    """True when the cache's known range does not yet reach close to
    `now_ms`: a capped sync (mega-fill wallet) is still catching up, so
    this pass's stats may be missing some of the most recent fills. Same
    user-facing flag as HL's own 10k-row cap (M.fills_truncated), different
    cause: both mean "not every fill in the window is visible yet"."""
    cov = db.get_fills_coverage(conn, wallet)
    return cov is not None and (now_ms - cov["last_ms"]) > slack_ms


def ensure_liquidation_backfilled(conn: sqlite3.Connection, venue: Venue, wallet: str) -> bool:
    """One-time per wallet: fills cached before the `liquidation` column
    existed (contract v13) were written with it hard-0 regardless of HL's
    real flag on that fill, so every liquidation older than the column's
    rollout reads as an ordinary close. `fills_coverage.liq_backfilled`
    marks a wallet done; a brand-new wallet (sync_fills' `cov is None`
    branch) is marked done immediately since its first-ever fetch already
    has the real flag, so this only ever does real work for a wallet synced
    before this feature shipped, and only once.

    Refetches the wallet's whole cached window [first_ms, last_ms] (same
    aggregateByTime call sync_fills already makes -- same page cost, same
    rate limiter, same background HL priority through the caller's venue)
    and upserts just the `liquidation` column onto the rows already cached.
    Soft-fail: a failed read here must not fail the wallet's stage-B build
    (its fills/stats are already correct without this) -- it just tries
    again next cycle, same as `extras`/`funding` being optional reads.

    Returns whether a refetch actually ran (for tests; callers don't need
    to branch on it, this only ever runs once and self-marks done)."""
    cov = db.get_fills_coverage(conn, wallet)
    if cov is None or cov.get("liq_backfilled"):
        return False
    try:
        rows = _fetch(venue, wallet, cov["first_ms"], cov["last_ms"])   # same aggregateByTime path as sync_fills
    except FillsFetchError:
        return False   # transient failure: try again next cycle, not marked done
    db.upsert_liquidation_flags(conn, wallet, rows)
    db.mark_liq_backfilled(conn, wallet)
    return True
