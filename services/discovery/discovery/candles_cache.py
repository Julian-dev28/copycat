"""Candle cache: data/discovery.db, keyed by (coin, interval, t_ms).

Shared across every wallet in a run. Candles are the expensive, high-volume
side of discovery (a 30-day 1m window is 43,200 bars per coin) and many
leaders trade the same handful of coins (BTC, ETH, SOL, ...), so caching by
coin instead of by wallet collapses most of the redundant work. Batched:
missing ranges are fetched in as few venue.candles() calls as the venue's
own page size allows, not one call per bar.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from contracts.venue import Venue

from . import db

_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}

MAX_BARS_PER_CALL = 5000  # conservative page size; page forward if a venue caps responses


def interval_ms(interval: str) -> int:
    try:
        return _INTERVAL_MS[interval]
    except KeyError:
        raise ValueError(f"unknown candle interval: {interval!r}") from None


def _parse_candle(row: Dict[str, Any]) -> Dict[str, float]:
    """HL candleSnapshot rows use t/T/o/h/l/c/v (o/h/l/c/v often strings)."""
    t = row.get("t_ms", row.get("t", row.get("time")))
    return {
        "t_ms": int(t),
        "o": float(row["o"]),
        "h": float(row["h"]),
        "l": float(row["l"]),
        "c": float(row["c"]),
        "v": float(row.get("v", 0.0)),
    }


def ensure_cached(conn: sqlite3.Connection, venue: Venue, coin: str, interval: str,
                   start_ms: int, end_ms: int) -> None:
    """Fetch and persist whatever part of [start_ms, end_ms] isn't cached yet."""
    step = interval_ms(interval)
    gaps = db.candle_coverage_gaps(conn, coin, interval, start_ms, end_ms, step)
    for gap_start, gap_end in gaps:
        cursor = gap_start
        span_cap = step * MAX_BARS_PER_CALL
        while cursor <= gap_end:
            chunk_end = min(gap_end, cursor + span_cap)
            raw = venue.candles(coin, interval, cursor, chunk_end)
            if not raw:
                break
            parsed = [_parse_candle(r) for r in raw]
            db.insert_candles(conn, coin, interval, parsed)
            max_t = max(p["t_ms"] for p in parsed)
            if max_t < cursor:
                break
            cursor = max_t + step
            if len(raw) < 2:
                break


def get_candles(conn: sqlite3.Connection, venue: Venue, coin: str, interval: str,
                 start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    ensure_cached(conn, venue, coin, interval, start_ms, end_ms)
    return db.get_cached_candles(conn, coin, interval, start_ms, end_ms)
