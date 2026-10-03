"""Candle cache and the mixed-resolution price series the sim walks.

HL's candleSnapshot only serves the most recent ~5000 bars of each interval
(measured 2026-10-03: 1m reaches back 3.5 days, 5m 17.4 days, 15m 52 days,
asking for older bars returns nothing). So a 30-day sim cannot run on 1m
bars. The series is tiered by age, finest first:

    1m   for the last TIER_BARS minutes        (~3.4 days)
    15m  older than that, up to ~51 days
    1h   older still

Boundaries come from the run's now_ms and are snapped up to the coarser
interval, so tiers never overlap. Each tier is fetched only over the spans
where the leader actually held a position that opened in the window
(positions.trip_spans): coins and periods with no possible copy cost
nothing.

`candle_coverage` records the ranges HL successfully answered, so bars HL
does not have (older than its window, or minutes with no trades on an
illiquid HIP-3 market) are not re-requested every run. The newest bar is
still forming when fetched, so coverage stops one bar short of now and the
next run refreshes it.
"""
from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from contracts.venue import Venue

from . import db

_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}

HL_MAX_BARS = 5000            # what HL serves per interval, newest first
TIER_BARS = 4900              # keep a margin under HL_MAX_BARS: a bar HL dropped since is not a gap
TIERS = ("1m", "15m", "1h")   # finest first
COARSE_LOOKAHEAD_MS = 86_400_000   # coarse tiers are fetched 1 day into the finer tier so a
                                   # re-run hours later (boundary moved) is still a cache hit

_coin_locks: Dict[str, threading.Lock] = {}
_coin_locks_guard = threading.Lock()


def interval_ms(interval: str) -> int:
    try:
        return _INTERVAL_MS[interval]
    except KeyError:
        raise ValueError(f"unknown candle interval: {interval!r}") from None


def _coin_lock(coin: str) -> threading.Lock:
    with _coin_locks_guard:
        return _coin_locks.setdefault(coin, threading.Lock())


def tier_bounds(now_ms: int, tiers: Tuple[str, ...] = TIERS) -> List[Tuple[str, int, int]]:
    """[(interval, lo_ms, hi_ms)] half-open ranges [lo, hi), finest first.
    Tier i covers [boundary_i, boundary_{i-1}); boundary_i is now minus
    TIER_BARS bars of tier i, snapped UP to tier i+1's step so the coarser
    tier's bars end exactly where the finer tier starts."""
    out: List[Tuple[str, int, int]] = []
    hi = now_ms + interval_ms(tiers[0])
    for i, iv in enumerate(tiers):
        if i == len(tiers) - 1:
            out.append((iv, 0, hi))
            break
        coarse = interval_ms(tiers[i + 1])
        raw = now_ms - TIER_BARS * interval_ms(iv)
        lo = int(math.ceil(raw / coarse) * coarse)
        out.append((iv, lo, hi))
        hi = lo
    return out


def _parse_candle(row: Dict[str, Any]) -> Dict[str, float]:
    """HL candleSnapshot rows use t/T/o/h/l/c/v (o/h/l/c/v strings)."""
    t = row.get("t_ms", row.get("t", row.get("time")))
    return {"t_ms": int(t), "o": float(row["o"]), "h": float(row["h"]), "l": float(row["l"]),
            "c": float(row["c"]), "v": float(row.get("v", 0.0))}


def ensure_cached(conn: sqlite3.Connection, venue: Venue, coin: str, interval: str,
                  start_ms: int, end_ms: int, now_ms: int, fresh_s: float = 0.0,
                  stats: Optional[Dict[str, int]] = None) -> bool:
    """Fetch whatever part of [start_ms, end_ms] is outside recorded coverage.
    False if any fetch failed (coverage untouched for that piece)."""
    step = interval_ms(interval)
    start_ms = (start_ms // step) * step
    end_ms = min(end_ms, now_ms)
    if end_ms < start_ms:
        return True
    have = db.get_candle_coverage(conn, coin, interval)
    if fresh_s > 0:
        # a coverage range ending within fresh_s of the forming bar counts as reaching now
        have = [(a, end_ms if b >= now_ms - step - fresh_s * 1000 else b) for a, b in have]
    ok = True
    for gap_lo, gap_hi in db.subtract_ranges((start_ms, end_ms), have):
        cursor = gap_lo
        while cursor <= gap_hi:
            chunk_hi = min(gap_hi, cursor + step * (HL_MAX_BARS - 1))
            raw = venue.candles(coin, interval, cursor, chunk_hi)
            if stats is not None:
                stats["candle_calls"] = stats.get("candle_calls", 0) + 1
            if raw is None:
                ok = False
                break
            parsed = [_parse_candle(r) for r in raw]
            if parsed:
                db.insert_candles(conn, coin, interval, parsed)
            # never mark the still-forming bar as final
            covered_hi = min(chunk_hi, now_ms - step - 1)
            db.add_candle_coverage(conn, coin, interval, cursor, covered_hi, join_gap=step)
            cursor = chunk_hi + 1
    return ok


@dataclass
class Series:
    """One coin's mixed-resolution bars, sorted by start time, non-overlapping."""
    t: List[int] = field(default_factory=list)
    end: List[int] = field(default_factory=list)
    o: List[float] = field(default_factory=list)
    h: List[float] = field(default_factory=list)
    l: List[float] = field(default_factory=list)
    c: List[float] = field(default_factory=list)
    step: List[int] = field(default_factory=list)

    def append(self, t: int, step: int, o: float, h: float, l: float, c: float) -> None:
        self.t.append(t)
        self.end.append(t + step)
        self.o.append(o)
        self.h.append(h)
        self.l.append(l)
        self.c.append(c)
        self.step.append(step)

    def __len__(self) -> int:
        return len(self.t)


def _tier_pieces(spans: List[Tuple[int, int]], now_ms: int) -> List[Tuple[str, int, int]]:
    pieces: List[Tuple[str, int, int]] = []
    bounds = tier_bounds(now_ms)
    for a, b in db.merge_ranges(spans):
        for i, (iv, lo, hi) in enumerate(bounds):
            fetch_hi = hi + (COARSE_LOOKAHEAD_MS if i > 0 else 0)
            x, y = max(a, lo), min(b, fetch_hi)
            if x <= y:
                pieces.append((iv, x, y))
    return pieces


def build_series(conn: sqlite3.Connection, venue: Venue, coin: str, spans: List[Tuple[int, int]],
                 now_ms: int, fresh_s: float = 0.0,
                 stats: Optional[Dict[str, int]] = None) -> Tuple[Series, bool]:
    """Fetch (if needed) and assemble the tiered series covering `spans`.
    Returns (series, ok); ok False means some fetch failed."""
    ok = True
    with _coin_lock(coin):
        for iv, x, y in _tier_pieces(spans, now_ms):
            ok = ensure_cached(conn, venue, coin, iv, x, y, now_ms, fresh_s, stats) and ok
    s = Series()
    if not spans:
        return s, ok
    a = min(x for x, _ in spans)
    b = max(y for _, y in spans)
    for iv, lo, hi in reversed(tier_bounds(now_ms)):   # coarsest (oldest) first
        step = interval_ms(iv)
        x, y = max(a - step, lo), min(b, hi - 1)
        if x > y:
            continue
        for r in db.get_cached_candles(conn, coin, iv, x, y):
            if r["t_ms"] + step > hi and iv != TIERS[0]:
                continue   # would overlap the finer tier
            s.append(int(r["t_ms"]), step, r["o"], r["h"], r["l"], r["c"])
    return s, ok


def get_candles(conn: sqlite3.Connection, venue: Venue, coin: str, interval: str,
                start_ms: int, end_ms: int, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    """Single-interval read-through (kept for tooling and tests)."""
    now_ms = now_ms if now_ms is not None else end_ms + interval_ms(interval) + 1
    ensure_cached(conn, venue, coin, interval, start_ms, end_ms, now_ms)
    return db.get_cached_candles(conn, coin, interval, start_ms, end_ms)
