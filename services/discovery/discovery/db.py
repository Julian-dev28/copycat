"""sqlite persistence for discovery: data/discovery.db.

Everything the service needs to survive a restart lives here: the fills
cache (per wallet, incremental), the candle cache (per coin+interval, shared
across every wallet that touches that coin), and discovery runs + their
ranked results.

Single-writer, single-file sqlite in WAL mode. The background run thread
(see discovery.public) is the only writer during a run; reads from the api
or CLI are safe to interleave because of WAL.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills_cursor (
    wallet TEXT PRIMARY KEY,
    last_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    wallet TEXT NOT NULL,
    time_ms INTEGER NOT NULL,
    coin TEXT NOT NULL,
    px REAL NOT NULL,
    sz REAL NOT NULL,
    side TEXT NOT NULL,
    dir TEXT,
    start_position REAL NOT NULL,
    closed_pnl REAL NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (wallet, time_ms, coin, side, sz, px)
);
CREATE INDEX IF NOT EXISTS idx_fills_wallet_time ON fills (wallet, time_ms);

CREATE TABLE IF NOT EXISTS candles (
    coin TEXT NOT NULL,
    interval TEXT NOT NULL,
    t_ms INTEGER NOT NULL,
    o REAL NOT NULL,
    h REAL NOT NULL,
    l REAL NOT NULL,
    c REAL NOT NULL,
    v REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (coin, interval, t_ms)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_ms INTEGER NOT NULL,
    finished_ms INTEGER,
    status TEXT NOT NULL,
    sim_equity_usd REAL NOT NULL,
    top_n INTEGER NOT NULL,
    sim_settings_json TEXT NOT NULL,
    candidates INTEGER NOT NULL DEFAULT 0,
    scored INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS results (
    run_id TEXT NOT NULL,
    address TEXT NOT NULL,
    score REAL NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, address)
);
CREATE INDEX IF NOT EXISTS idx_results_run_score ON results (run_id, score);
"""

_local = threading.local()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """One connection per (thread, path). sqlite connections are not
    thread-safe to share; the background run thread and the calling thread
    (api/CLI) each get their own."""
    key = f"{threading.get_ident()}:{db_path}"
    conn = getattr(_local, key, None)
    if conn is not None:
        return conn
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    setattr(_local, key, conn)
    return conn


# ── fills ─────────────────────────────────────────────────────────────────

def get_fills_cursor(conn: sqlite3.Connection, wallet: str) -> Optional[int]:
    row = conn.execute("SELECT last_ms FROM fills_cursor WHERE wallet = ?", (wallet,)).fetchone()
    return int(row["last_ms"]) if row else None


def set_fills_cursor(conn: sqlite3.Connection, wallet: str, last_ms: int) -> None:
    conn.execute(
        "INSERT INTO fills_cursor (wallet, last_ms) VALUES (?, ?) "
        "ON CONFLICT(wallet) DO UPDATE SET last_ms = excluded.last_ms",
        (wallet, last_ms),
    )
    conn.commit()


def insert_fills(conn: sqlite3.Connection, wallet: str, fills: List[Dict[str, Any]]) -> int:
    """INSERT OR IGNORE: the composite key dedupes retried/overlapping fetches.
    Two genuinely distinct fills for the same wallet at the same millisecond,
    same coin, same side, same size and same price would collide and the
    second would be dropped; this is a documented, accepted approximation
    (see README) since HL fills carry no other stable id in our Fill
    contract."""
    n = 0
    for f in fills:
        cur = conn.execute(
            "INSERT OR IGNORE INTO fills "
            "(wallet, time_ms, coin, px, sz, side, dir, start_position, closed_pnl, fee) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                wallet, int(f["time_ms"]), f["coin"], float(f["px"]), float(f["sz"]),
                f["side"], f.get("dir"), float(f["start_position"]),
                float(f.get("closed_pnl", 0.0)), float(f.get("fee", 0.0)),
            ),
        )
        n += cur.rowcount
    conn.commit()
    return n


def get_cached_fills(conn: sqlite3.Connection, wallet: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM fills WHERE wallet = ? AND time_ms >= ? AND time_ms <= ? ORDER BY time_ms ASC",
        (wallet, start_ms, end_ms),
    ).fetchall()
    return [dict(r) for r in rows]


# ── candles ───────────────────────────────────────────────────────────────

def insert_candles(conn: sqlite3.Connection, coin: str, interval: str, rows: List[Dict[str, Any]]) -> int:
    n = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO candles (coin, interval, t_ms, o, h, l, c, v) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (coin, interval, int(r["t_ms"]), float(r["o"]), float(r["h"]), float(r["l"]),
             float(r["c"]), float(r.get("v", 0.0))),
        )
        n += cur.rowcount
    conn.commit()
    return n


def get_cached_candles(conn: sqlite3.Connection, coin: str, interval: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM candles WHERE coin = ? AND interval = ? AND t_ms >= ? AND t_ms <= ? ORDER BY t_ms ASC",
        (coin, interval, start_ms, end_ms),
    ).fetchall()
    return [dict(r) for r in rows]


def candle_coverage_gaps(conn: sqlite3.Connection, coin: str, interval: str, start_ms: int,
                          end_ms: int, step_ms: int) -> List[tuple[int, int]]:
    """Return a minimal list of [start, end] sub-ranges within [start_ms, end_ms]
    that are NOT fully covered by cached candles, so callers only fetch what's
    missing. Deterministic set-difference over expected bar timestamps."""
    have = {
        int(r["t_ms"]) for r in conn.execute(
            "SELECT t_ms FROM candles WHERE coin = ? AND interval = ? AND t_ms >= ? AND t_ms <= ?",
            (coin, interval, start_ms, end_ms),
        ).fetchall()
    }
    expected = range(start_ms, end_ms + 1, step_ms)
    missing = [t for t in expected if t not in have]
    if not missing:
        return []
    gaps: List[tuple[int, int]] = []
    gap_start = missing[0]
    prev = missing[0]
    for t in missing[1:]:
        if t - prev > step_ms:
            gaps.append((gap_start, prev))
            gap_start = t
        prev = t
    gaps.append((gap_start, prev))
    return gaps


# ── runs ──────────────────────────────────────────────────────────────────

def create_run(conn: sqlite3.Connection, run_id: str, started_ms: int, sim_equity_usd: float,
               top_n: int, sim_settings_json: str) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, started_ms, status, sim_equity_usd, top_n, sim_settings_json, "
        "candidates, scored) VALUES (?, ?, 'running', ?, ?, ?, 0, 0)",
        (run_id, started_ms, sim_equity_usd, top_n, sim_settings_json),
    )
    conn.commit()


def update_run(conn: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {cols} WHERE run_id = ?", (*fields.values(), run_id))
    conn.commit()


def save_result(conn: sqlite3.Connection, run_id: str, address: str, score: float, payload_json: str) -> None:
    conn.execute(
        "INSERT INTO results (run_id, address, score, payload_json) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(run_id, address) DO UPDATE SET score = excluded.score, payload_json = excluded.payload_json",
        (run_id, address, score, payload_json),
    )
    conn.commit()


def get_run_row(conn: sqlite3.Connection, run_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_results(conn: sqlite3.Connection, run_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT payload_json FROM results WHERE run_id = ? ORDER BY score DESC", (run_id,)
    ).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def latest_run_id(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT run_id FROM runs ORDER BY started_ms DESC LIMIT 1").fetchone()
    return row["run_id"] if row else None
