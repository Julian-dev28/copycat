"""sqlite persistence for discovery: data/discovery.db.

Everything the service needs to survive a restart lives here: the fills
cache (per wallet, coverage-tracked, incremental), the candle cache (per
coin+interval, coverage-tracked, shared across every wallet), a leaderboard
snapshot cache, and discovery runs + their ranked results.

Coverage, not "rows present", decides a cache hit. HL only serves the most
recent ~5000 bars per candle interval, and illiquid markets skip bars with
no trades, so "every expected bar is on disk" is never true for most
ranges; the old row-based gap check refetched those holes on every run.
`fills_coverage` / `candle_coverage` record the ranges we asked HL for and
got a successful answer; a failed fetch records nothing.

WAL mode: readers (api, CLI) never block the run's writers. Each thread
gets its own connection (see `connect`).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills_coverage (
    wallet TEXT PRIMARY KEY,
    first_ms INTEGER NOT NULL,
    last_ms INTEGER NOT NULL,
    fetched_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fills_v2 (
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
    PRIMARY KEY (wallet, time_ms, coin, side, sz, px, start_position)
);
CREATE INDEX IF NOT EXISTS idx_fills_v2_wallet_time ON fills_v2 (wallet, time_ms);

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

CREATE TABLE IF NOT EXISTS candle_coverage (
    coin TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    PRIMARY KEY (coin, interval, start_ms)
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL,
    v TEXT NOT NULL
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

# Columns added after the first schema. sqlite has no ADD COLUMN IF NOT EXISTS.
_MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN heartbeat_ms INTEGER",
    "ALTER TABLE runs ADD COLUMN params_json TEXT",
]

_local = threading.local()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """One connection per (thread, path): sqlite connections are not safe
    to share across threads."""
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
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass   # already migrated
    conn.commit()
    setattr(_local, key, conn)
    return conn


# ── closed-range arithmetic ───────────────────────────────────────────────

def subtract_ranges(want: Tuple[int, int], have: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Parts of closed range `want` not covered by any closed range in `have`."""
    lo, hi = want
    if hi < lo:
        return []
    out: List[Tuple[int, int]] = []
    cur = lo
    for a, b in sorted(have):
        if b < cur:
            continue
        if a > hi:
            break
        if a > cur:
            out.append((cur, min(hi, a - 1)))
        cur = max(cur, b + 1)
        if cur > hi:
            break
    if cur <= hi:
        out.append((cur, hi))
    return out


def merge_ranges(ranges: List[Tuple[int, int]], join_gap: int = 1) -> List[Tuple[int, int]]:
    """Union of closed ranges; ranges within `join_gap` of each other are joined."""
    out: List[Tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + join_gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# ── fills ─────────────────────────────────────────────────────────────────

def get_fills_coverage(conn: sqlite3.Connection, wallet: str) -> Optional[Dict[str, int]]:
    row = conn.execute("SELECT first_ms, last_ms, fetched_ms FROM fills_coverage WHERE wallet = ?",
                       (wallet,)).fetchone()
    return dict(row) if row else None


def set_fills_coverage(conn: sqlite3.Connection, wallet: str, first_ms: int, last_ms: int,
                       fetched_ms: int) -> None:
    conn.execute(
        "INSERT INTO fills_coverage (wallet, first_ms, last_ms, fetched_ms) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(wallet) DO UPDATE SET first_ms = excluded.first_ms, last_ms = excluded.last_ms, "
        "fetched_ms = excluded.fetched_ms",
        (wallet, first_ms, last_ms, fetched_ms),
    )
    conn.commit()


def insert_fills(conn: sqlite3.Connection, wallet: str, fills: List[Dict[str, Any]]) -> int:
    """INSERT OR IGNORE: the composite key dedupes overlapping fetches. It
    includes start_position: a TWAP/iceberg leader produces many fills at
    the same ms, size and price, and without it those collapsed into one
    (the v1 `fills` table). Two fills can now only collide if they also
    started from the identical position, which a real fill sequence can't
    do (each fill moves the position)."""
    rows = [
        (wallet, int(f["time_ms"]), f["coin"], float(f["px"]), float(f["sz"]), f["side"],
         f.get("dir"), float(f["start_position"]), float(f.get("closed_pnl", 0.0)),
         float(f.get("fee", 0.0)))
        for f in fills
    ]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO fills_v2 "
        "(wallet, time_ms, coin, px, sz, side, dir, start_position, closed_pnl, fee) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return conn.total_changes - before


def get_cached_fills(conn: sqlite3.Connection, wallet: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM fills_v2 WHERE wallet = ? AND time_ms >= ? AND time_ms <= ? ORDER BY time_ms ASC",
        (wallet, start_ms, end_ms),
    ).fetchall()
    return [dict(r) for r in rows]


# ── candles ───────────────────────────────────────────────────────────────

def insert_candles(conn: sqlite3.Connection, coin: str, interval: str, rows: List[Dict[str, Any]]) -> int:
    """INSERT OR REPLACE: the newest bar is still forming when fetched and a
    later fetch must overwrite it with its final values."""
    data = [(coin, interval, int(r["t_ms"]), float(r["o"]), float(r["h"]), float(r["l"]),
             float(r["c"]), float(r.get("v", 0.0))) for r in rows]
    conn.executemany(
        "INSERT OR REPLACE INTO candles (coin, interval, t_ms, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        data)
    conn.commit()
    return len(data)


def get_cached_candles(conn: sqlite3.Connection, coin: str, interval: str, start_ms: int,
                       end_ms: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT t_ms, o, h, l, c, v FROM candles WHERE coin = ? AND interval = ? AND t_ms >= ? AND t_ms <= ? "
        "ORDER BY t_ms ASC",
        (coin, interval, start_ms, end_ms),
    ).fetchall()
    return [dict(r) for r in rows]


def get_candle_coverage(conn: sqlite3.Connection, coin: str, interval: str) -> List[Tuple[int, int]]:
    rows = conn.execute("SELECT start_ms, end_ms FROM candle_coverage WHERE coin = ? AND interval = ? "
                        "ORDER BY start_ms", (coin, interval)).fetchall()
    return [(int(r["start_ms"]), int(r["end_ms"])) for r in rows]


def add_candle_coverage(conn: sqlite3.Connection, coin: str, interval: str, start_ms: int, end_ms: int,
                        join_gap: int = 1) -> None:
    if end_ms < start_ms:
        return
    merged = merge_ranges(get_candle_coverage(conn, coin, interval) + [(start_ms, end_ms)], join_gap=join_gap)
    conn.execute("DELETE FROM candle_coverage WHERE coin = ? AND interval = ?", (coin, interval))
    conn.executemany("INSERT INTO candle_coverage (coin, interval, start_ms, end_ms) VALUES (?, ?, ?, ?)",
                     [(coin, interval, a, b) for a, b in merged])
    conn.commit()


# ── kv (leaderboard snapshot) ─────────────────────────────────────────────

def kv_get(conn: sqlite3.Connection, k: str) -> Optional[Tuple[int, Any]]:
    row = conn.execute("SELECT ts_ms, v FROM kv WHERE k = ?", (k,)).fetchone()
    return (int(row["ts_ms"]), json.loads(row["v"])) if row else None


def kv_set(conn: sqlite3.Connection, k: str, ts_ms: int, v: Any) -> None:
    conn.execute("INSERT INTO kv (k, ts_ms, v) VALUES (?, ?, ?) "
                 "ON CONFLICT(k) DO UPDATE SET ts_ms = excluded.ts_ms, v = excluded.v",
                 (k, ts_ms, json.dumps(v)))
    conn.commit()


# ── runs ──────────────────────────────────────────────────────────────────

def create_run(conn: sqlite3.Connection, run_id: str, started_ms: int, sim_equity_usd: float,
               top_n: int, sim_settings_json: str, params_json: str = "{}") -> None:
    conn.execute(
        "INSERT INTO runs (run_id, started_ms, status, sim_equity_usd, top_n, sim_settings_json, "
        "candidates, scored, heartbeat_ms, params_json) VALUES (?, ?, 'running', ?, ?, ?, 0, 0, ?, ?)",
        (run_id, started_ms, sim_equity_usd, top_n, sim_settings_json, started_ms, params_json),
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


def running_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM runs WHERE status = 'running'").fetchall()]
