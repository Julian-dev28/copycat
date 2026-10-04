"""Thesis tables in data/discovery.db (same WAL file as the fills and candle
caches the fingerprint reads, so one connection serves both).

    thesis_fingerprints  (address, window_days) -> latest StrategyFingerprint JSON
    thesis_texts         (address, source)      -> latest Thesis JSON, one per source

TTL lives in the reader (`get_fingerprint(max_age_s=...)`): rows are kept
forever and simply ignored once older than the TTL, so a stale row is
still there for debugging. Nothing else in discovery reads or writes these.
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from contracts.models import StrategyFingerprint, Thesis

SCHEMA = """
CREATE TABLE IF NOT EXISTS thesis_fingerprints (
    address TEXT NOT NULL,
    window_days INTEGER NOT NULL,
    as_of_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (address, window_days)
);
CREATE TABLE IF NOT EXISTS thesis_texts (
    address TEXT NOT NULL,
    source TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (address, source)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def put_fingerprint(conn: sqlite3.Connection, fp: StrategyFingerprint) -> None:
    conn.execute(
        "INSERT INTO thesis_fingerprints (address, window_days, as_of_ms, payload_json) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(address, window_days) DO UPDATE SET as_of_ms = excluded.as_of_ms, "
        "payload_json = excluded.payload_json",
        (fp.address.lower(), fp.window_days, fp.as_of_ms, fp.model_dump_json()))
    conn.commit()


def get_fingerprint(conn: sqlite3.Connection, address: str, window_days: int, now_ms: int,
                    max_age_s: float) -> Optional[StrategyFingerprint]:
    """The stored fingerprint if it is at most max_age_s old (max_age_s < 0: any age)."""
    row = conn.execute("SELECT as_of_ms, payload_json FROM thesis_fingerprints WHERE address = ? AND "
                       "window_days = ?", (address.lower(), window_days)).fetchone()
    if row is None:
        return None
    if max_age_s >= 0 and now_ms - int(row[0]) > max_age_s * 1000:
        return None
    return StrategyFingerprint.model_validate_json(row[1])


def put_thesis(conn: sqlite3.Connection, t: Thesis) -> None:
    """Latest per (address, source): a newer save replaces the older one."""
    conn.execute(
        "INSERT INTO thesis_texts (address, source, created_ms, payload_json) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(address, source) DO UPDATE SET created_ms = excluded.created_ms, "
        "payload_json = excluded.payload_json",
        (t.address.lower(), t.source, t.created_ms, t.model_dump_json()))
    conn.commit()


def list_theses(conn: sqlite3.Connection, address: str) -> List[Thesis]:
    """Newest first; source name breaks ties."""
    rows = conn.execute("SELECT payload_json FROM thesis_texts WHERE address = ? "
                        "ORDER BY created_ms DESC, source ASC", (address.lower(),)).fetchall()
    return [Thesis.model_validate_json(r[0]) for r in rows]
