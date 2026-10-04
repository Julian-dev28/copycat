"""discovery.thesis.public: the only surface other services import.

    fingerprint(address, window_days=30, venue=None) -> StrategyFingerprint
    ta_thesis(address, fingerprint=None)             -> Thesis (source "ta")
    save_thesis(thesis)                              -> None  (latest per source kept)
    get_theses(address)                              -> List[Thesis]

I/O lives here; every number comes from the pure `fingerprint.build_fingerprint`.
Reads go through the shared caches in data/discovery.db (fills_cache,
candles_cache) and draw from the HL budget as a "background" caller.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from contracts.models import StrategyFingerprint, Thesis, norm_addr

from .. import candles_cache, db, fills_cache, positions
from . import config as C
from . import store
from .fingerprint import build_fingerprint
from .indicators import Bars
from .template import render_markdown, render_title

logger = logging.getLogger(__name__)
_ADDR = re.compile(r"^0x[0-9a-f]{40}$")


class ThesisError(RuntimeError):
    """A read the fingerprint cannot do without failed (fills)."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _addr(address: str) -> str:
    a = norm_addr(address)
    if not _ADDR.match(a):
        raise ValueError(f"not a 0x address: {address!r}")
    return a


def _conn(conn: Optional[sqlite3.Connection] = None) -> sqlite3.Connection:
    return store.ensure_schema(conn if conn is not None else db.connect(C.db_path()))


def use_background_priority() -> None:
    """Same as discovery.public.use_background_priority (copied, not imported,
    so this package does not pull in the run machinery)."""
    os.environ["COPYCAT_HL_PRIORITY"] = "background"
    try:
        from hl import rate_limit
    except ImportError:
        return
    if getattr(getattr(rate_limit, "HL_LIMITER", None), "priority", None) != "background":
        rate_limit.set_priority("background")


def _default_venue() -> Any:
    use_background_priority()
    from hl import HlVenue
    return HlVenue()


# ── reads ─────────────────────────────────────────────────────────────────

def equity_points(venue: Any, address: str, now_ms: int) -> Tuple[List[Tuple[int, float]], List[str]]:
    """Account value history from HL `portfolio` (month + allTime merged,
    finest wins on equal timestamps). Falls back to the current account
    value as one point, with a caveat."""
    pts: Dict[int, float] = {}
    raw = None
    fn = getattr(venue, "portfolio", None)
    if callable(fn):
        try:
            raw = fn(address)
        except Exception as exc:   # a failed read is a caveat, not a crash
            logger.warning("thesis: portfolio read failed for %s: %s", address, exc)
    for pair in raw or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[1], dict)):
            continue
        if pair[0] not in ("month", "allTime"):
            continue
        for p in pair[1].get("accountValueHistory") or []:
            try:
                t, v = int(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                continue
            if pair[0] == "month" or t not in pts:
                pts[t] = v
    if any(v > 0 for v in pts.values()):
        return sorted(pts.items()), []
    state = None
    try:
        state = venue.account_state(address)
    except Exception as exc:
        logger.warning("thesis: account_state read failed for %s: %s", address, exc)
    eq = float((state or {}).get("equity_perp_usd") or 0.0) + float((state or {}).get("spot_usdc") or 0.0)
    if eq > 0:
        return [(now_ms, eq)], ["Account value history unavailable; leverage uses today's account value."]
    return [], []


def load_bars(conn: sqlite3.Connection, venue: Any, coin: str, entries_ms: List[int],
              now_ms: int) -> Tuple[Optional[Bars], bool]:
    """1h bars from WARMUP_BARS + 2 hours before the first entry to the last
    entry, through the shared candle cache. (bars or None, fetch ok)."""
    if not entries_ms or not positions.is_perp_coin(coin):
        return None, True
    lo = min(entries_ms) - (C.WARMUP_BARS + 2) * C.HOUR_MS
    hi = max(entries_ms)
    ok = candles_cache.ensure_cached(conn, venue, coin, C.CANDLE_INTERVAL, lo, hi, now_ms,
                                     fresh_s=C.FILLS_FRESH_S)
    rows = db.get_cached_candles(conn, coin, C.CANDLE_INTERVAL, lo, hi)
    return (Bars.from_rows(rows) if rows else None), ok


# ── public surface ────────────────────────────────────────────────────────

def compute_fingerprint(address: str, window_days: int, venue: Any, conn: sqlite3.Connection,
                        now_ms: int) -> StrategyFingerprint:
    """Always recomputes (fills tail + candles through the caches)."""
    from .trips import build_trips
    try:
        fills = fills_cache.sync_fills(conn, venue, address, window_days, now_ms, fresh_s=C.FILLS_FRESH_S)
    except fills_cache.FillsFetchError as exc:
        raise ThesisError(str(exc)) from exc
    trips, _ = build_trips(fills)
    entries: Dict[str, List[int]] = {}
    for t in trips:
        entries.setdefault(t.coin, []).append(t.opened_ms)
    bars: Dict[str, Optional[Bars]] = {}
    failed: List[str] = []
    for coin in sorted(entries):
        b, ok = load_bars(conn, venue, coin, entries[coin], now_ms)
        bars[coin] = b
        if not ok:
            failed.append(coin)
    eq, caveats = equity_points(venue, address, now_ms)
    if failed:
        caveats.append(f"1h candle read failed for {', '.join(failed)}; those entries may lack context.")
    return build_fingerprint(address, fills, bars, eq, window_days, now_ms, caveats)


def fingerprint(address: str, window_days: int = C.DEFAULT_WINDOW_DAYS, venue: Optional[Any] = None, *,
                refresh: bool = False, max_age_s: Optional[float] = None,
                conn: Optional[sqlite3.Connection] = None, now_ms: Optional[int] = None) -> StrategyFingerprint:
    """The stored fingerprint when younger than the TTL (COPYCAT_THESIS_TTL_S,
    default 1h) unless refresh=True; else recompute and store it."""
    a = _addr(address)
    now_ms = now_ms if now_ms is not None else _now_ms()
    c = _conn(conn)
    ttl = C.FINGERPRINT_TTL_S if max_age_s is None else max_age_s
    if not refresh:
        hit = store.get_fingerprint(c, a, window_days, now_ms, ttl)
        if hit is not None:
            return hit
    if venue is None:
        venue = _default_venue()
    else:
        use_background_priority()
    fp = compute_fingerprint(a, window_days, venue, c, now_ms)
    store.put_fingerprint(c, fp)
    logger.info("thesis: fingerprint %s %dd trips=%d tags=%s", a, window_days, fp.trips_analyzed, fp.tags)
    return fp


def thesis_from_fingerprint(fp: StrategyFingerprint, now_ms: Optional[int] = None) -> Thesis:
    return Thesis(address=fp.address, source="ta", created_ms=now_ms if now_ms is not None else fp.as_of_ms,
                  title=render_title(fp), markdown=render_markdown(fp)[:20_000],
                  fingerprint_as_of_ms=fp.as_of_ms, author="copycat TA fingerprint (deterministic)")


def ta_thesis(address: str, fingerprint: Optional[StrategyFingerprint] = None, *,
              window_days: int = C.DEFAULT_WINDOW_DAYS, venue: Optional[Any] = None,
              conn: Optional[sqlite3.Connection] = None, now_ms: Optional[int] = None) -> Thesis:
    """The `ta` Thesis. Pass a fingerprint you already have to skip the
    recompute; otherwise the stored one is reused within its TTL. Saved as
    the latest `ta` thesis for the address."""
    a = _addr(address)
    c = _conn(conn)
    fp = fingerprint
    if fp is None or fp.address != a:
        fp = globals()["fingerprint"](a, window_days, venue, conn=c, now_ms=now_ms)
    t = thesis_from_fingerprint(fp)
    store.put_thesis(c, t)
    return t


def save_thesis(thesis: Thesis, conn: Optional[sqlite3.Connection] = None) -> None:
    """Store a thesis (the MCP server's `claude_code` ones arrive here via
    the api). Replaces the previous one of the same source."""
    t = thesis.model_copy(update={"address": _addr(thesis.address)})
    store.put_thesis(_conn(conn), t)


def get_theses(address: str, conn: Optional[sqlite3.Connection] = None) -> List[Thesis]:
    """Latest thesis per source, newest first."""
    return store.list_theses(_conn(conn), _addr(address))
