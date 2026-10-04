"""discovery.candles_public.candles: one-interval candle read-through for
the api's candles route, backed by the shared candle cache in
data/discovery.db. Re-exported by discovery.public.

    candles(coin, interval, start_ms, end_ms) -> [{t_ms, o, h, l, c, v}]

HL serves only the newest ~5000 bars per interval, so a range wider than
that is clamped to its newest 5000 bars. Bars HL does not have come back
missing (never invented). HL reads use the background priority.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import candles_cache, db

MAX_BARS = candles_cache.HL_MAX_BARS


def _db_path() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data")) / "discovery.db"


def _default_venue() -> Any:
    from .thesis.public import _default_venue as dv  # sets the background priority first
    return dv()


def candles(coin: str, interval: str, start_ms: int, end_ms: int, venue: Optional[Any] = None,
            conn: Optional[sqlite3.Connection] = None, now_ms: Optional[int] = None) -> List[Dict[str, float]]:
    step = candles_cache.interval_ms(interval)          # ValueError on an unknown interval
    if end_ms < start_ms:
        raise ValueError("end_ms before start_ms")
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    end_ms = min(end_ms, now_ms)
    start_ms = max(start_ms, end_ms - (MAX_BARS - 1) * step)
    c = conn if conn is not None else db.connect(_db_path())
    candles_cache.ensure_cached(c, venue if venue is not None else _default_venue(), coin, interval,
                                start_ms, end_ms, now_ms)
    return db.get_cached_candles(c, coin, interval, (start_ms // step) * step, end_ms)
