"""Scout's sqlite tables (spec 7.1), in data/discovery.db next to the fills
and candle caches it reuses. Same WAL file on purpose: stage B fills and
stage C candles land in the caches manual /discover runs read, and WAL
lets the api read while the scheduler writes.

Board switchover: `scout_rows` for a new build are written under a new
`refresh_id`; the pointer in `scout_meta` (current_refresh,
current_hash, ...) moves in ONE transaction only after every row is on
disk. A reader resolves the pointer first, then reads that refresh_id's
rows; the last KEEP_REFRESHES builds are retained, so a reader that
resolved the pointer just before a switch still finds its rows.

Tables owned here: scout_universe, scout_stats, scout_sim, scout_rows,
scout_refresh, scout_meta. Nothing else in discovery reads or writes them.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .. import db as discovery_db
from . import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_universe (
  address TEXT PRIMARY KEY, display_name TEXT, account_value REAL,
  pnl_1d REAL, pnl_7d REAL, pnl_30d REAL, pnl_all REAL,
  roi_1d REAL, roi_7d REAL, roi_30d REAL, roi_all REAL,
  vlm_1d REAL, vlm_7d REAL, vlm_30d REAL, vlm_all REAL,
  is_vault INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'lb', seen_ms INTEGER);

CREATE TABLE IF NOT EXISTS scout_stats (
  address TEXT PRIMARY KEY, updated_ms INTEGER,
  portfolio_json TEXT, account_json TEXT, positions_json TEXT, positions_ms INTEGER,
  stats_json TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0, skip_until_ms INTEGER NOT NULL DEFAULT 0,
  last_try_ms INTEGER NOT NULL DEFAULT 0, last_error TEXT);

CREATE TABLE IF NOT EXISTS scout_sim (
  address TEXT, settings_hash TEXT, sim_equity REAL, updated_ms INTEGER, stats_ms INTEGER,
  score_json TEXT, sim_curve_json TEXT,
  PRIMARY KEY (address, settings_hash, sim_equity));

CREATE TABLE IF NOT EXISTS scout_rows (
  refresh_id TEXT, settings_hash TEXT, address TEXT, display_name TEXT,
  fit REAL, sim_return REAL, sim_dd REAL,
  account_value REAL, pnl_1d REAL, pnl_7d REAL, pnl_30d REAL, pnl_all REAL,
  roi_1d REAL, roi_7d REAL, roi_30d REAL, roi_all REAL,
  vlm_1d REAL, vlm_7d REAL, vlm_30d REAL, vlm_all REAL,
  sharpe REAL, max_dd REAL, win_rate REAL, trips INTEGER,
  style TEXT, size_tier TEXT, last_fill_ms INTEGER,
  top_coin TEXT, hip3_share REAL, coins_csv TEXT, flags_csv TEXT, flagged INTEGER,
  row_json TEXT,
  PRIMARY KEY (refresh_id, settings_hash, address));
CREATE INDEX IF NOT EXISTS idx_scout_rows_fit ON scout_rows (refresh_id, settings_hash, fit DESC);
CREATE INDEX IF NOT EXISTS idx_scout_rows_pnl30 ON scout_rows (refresh_id, pnl_30d);
CREATE INDEX IF NOT EXISTS idx_scout_rows_roi30 ON scout_rows (refresh_id, roi_30d);
CREATE INDEX IF NOT EXISTS idx_scout_rows_av ON scout_rows (refresh_id, account_value);
CREATE INDEX IF NOT EXISTS idx_scout_rows_last ON scout_rows (refresh_id, last_fill_ms);

CREATE TABLE IF NOT EXISTS scout_refresh (
  refresh_id TEXT PRIMARY KEY, started_ms INTEGER, finished_ms INTEGER, heartbeat_ms INTEGER,
  state TEXT, stage TEXT, done INTEGER, total INTEGER, error TEXT, kind TEXT, eta_s REAL);

CREATE TABLE IF NOT EXISTS scout_requests (    -- on-demand trader files, built by `serve`
  address TEXT PRIMARY KEY, requested_ms INTEGER, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);

CREATE TABLE IF NOT EXISTS scout_meta (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS scout_departures (   -- survivorship trail (user_consensus P1 #7)
  address TEXT PRIMARY KEY, display_name TEXT, last_account_value REAL, last_pnl_30d REAL,
  had_liquidation INTEGER NOT NULL DEFAULT 0, last_seen_ms INTEGER, departed_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_scout_departures_ms ON scout_departures (departed_ms);

CREATE TABLE IF NOT EXISTS scout_custom (       -- v15: wallets the user added to the board by hand
  address TEXT PRIMARY KEY, added_ms INTEGER NOT NULL);
"""
# v16 (ScoutSimTerms) added no table: it lives in scout_meta under key "sim_terms", one
# JSON blob, read/written through sim_terms()/set_sim_terms() below like every other
# scout_meta value (wanted_hash, sim_hash, ...). No sentinel/migration needed for it.

ROW_COLUMNS = ("refresh_id", "settings_hash", "address", "display_name", "fit", "sim_return", "sim_dd",
               "account_value", "pnl_1d", "pnl_7d", "pnl_30d", "pnl_all",
               "roi_1d", "roi_7d", "roi_30d", "roi_all", "vlm_1d", "vlm_7d", "vlm_30d", "vlm_all",
               "sharpe", "max_dd", "win_rate", "trips", "style", "size_tier", "last_fill_ms",
               "top_coin", "hip3_share", "coins_csv", "flags_csv", "flagged", "row_json")

UNIVERSE_COLUMNS = ("address", "display_name", "account_value", "pnl_1d", "pnl_7d", "pnl_30d", "pnl_all",
                    "roi_1d", "roi_7d", "roi_30d", "roi_all", "vlm_1d", "vlm_7d", "vlm_30d", "vlm_all",
                    "is_vault", "source", "seen_ms")

_schema_lock = threading.Lock()


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Per-thread connection from discovery.db.connect (WAL, discovery's own
    schema) plus Scout's tables. Whether they exist is asked of the file each
    time (one indexed sqlite_master lookup): caching it by connection id was a
    bug, ids are reused after a connection is collected.

    The sentinel is the NEWEST table SCHEMA creates (currently
    scout_custom): a database that already has every older scout table
    but not this one still needs the (idempotent, CREATE TABLE IF NOT
    EXISTS) script run once. Bumping SCHEMA with a new table must move this
    sentinel to that table's name, or an existing data/discovery.db never
    gets it (caught live: scout_presets() 500'd with "no such table:
    scout_departures" against a database that predated it)."""
    conn = discovery_db.connect(path or C.db_path())
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scout_custom'").fetchone() is None:
        with _schema_lock:
            conn.executescript(SCHEMA)
            conn.commit()
    return conn


# ── meta ──────────────────────────────────────────────────────────────────

def meta_get(conn: sqlite3.Connection, k: str, default: Any = None) -> Any:
    row = conn.execute("SELECT v FROM scout_meta WHERE k = ?", (k,)).fetchone()
    return json.loads(row["v"]) if row else default


def meta_set(conn: sqlite3.Connection, items: Dict[str, Any], commit: bool = True) -> None:
    conn.executemany("INSERT INTO scout_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                     [(k, json.dumps(v)) for k, v in items.items()])
    if commit:
        conn.commit()


def sim_terms(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """The stored ScoutSimTerms (plain dict, validated by the caller), or None
    before anyone has ever called PUT /api/scout/sim-terms."""
    return meta_get(conn, "sim_terms")


def set_sim_terms(conn: sqlite3.Connection, terms: Dict[str, Any]) -> None:
    meta_set(conn, {"sim_terms": terms})


def pointer(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """The board build currently served, or None before the first build."""
    rows = conn.execute("SELECT k, v FROM scout_meta WHERE k IN ('current_refresh', 'current_hash', "
                        "'current_as_of', 'current_cohort', 'current_equity')").fetchall()
    d = {r["k"]: json.loads(r["v"]) for r in rows}
    if "current_refresh" not in d:
        return None
    return {"refresh_id": d["current_refresh"], "settings_hash": d.get("current_hash", ""),
            "as_of_ms": int(d.get("current_as_of") or 0), "cohort_size": int(d.get("current_cohort") or 0),
            "sim_equity": float(d.get("current_equity") or 0.0)}


# ── universe ──────────────────────────────────────────────────────────────

def replace_universe(conn: sqlite3.Connection, rows: Sequence[Dict[str, Any]], keep_sources: Iterable[str] = ()) -> None:
    """Swap the stage-A universe in one transaction. Rows whose source is in
    keep_sources (on-demand trader files) survive the swap."""
    keep = tuple(keep_sources)
    with conn:
        if keep:
            conn.execute(f"DELETE FROM scout_universe WHERE source NOT IN ({','.join('?' * len(keep))})", keep)
        else:
            conn.execute("DELETE FROM scout_universe")
        conn.executemany(
            f"INSERT OR REPLACE INTO scout_universe ({','.join(UNIVERSE_COLUMNS)}) "
            f"VALUES ({','.join('?' * len(UNIVERSE_COLUMNS))})",
            [tuple(r.get(c) for c in UNIVERSE_COLUMNS) for r in rows])


def upsert_universe(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    with conn:
        conn.execute(f"INSERT OR REPLACE INTO scout_universe ({','.join(UNIVERSE_COLUMNS)}) "
                     f"VALUES ({','.join('?' * len(UNIVERSE_COLUMNS))})", tuple(row.get(c) for c in UNIVERSE_COLUMNS))


BOARD_SOURCES = ("lb", "book", "custom")   # universe rows that form the board cohort ("ondemand" files do not)


def universe(conn: sqlite3.Connection, sources: Sequence[str] = BOARD_SOURCES) -> List[Dict[str, Any]]:
    q = f"SELECT * FROM scout_universe WHERE source IN ({','.join('?' * len(sources))}) ORDER BY pnl_30d DESC"
    return [dict(r) for r in conn.execute(q, tuple(sources)).fetchall()]


def delete_universe_row(conn: sqlite3.Connection, address: str, only_source: Optional[str] = None) -> bool:
    """Drop one universe row; with only_source, only when its source matches (a custom
    wallet that is also on the leaderboard keeps its lb row)."""
    with conn:
        if only_source is None:
            cur = conn.execute("DELETE FROM scout_universe WHERE address = ?", (address,))
        else:
            cur = conn.execute("DELETE FROM scout_universe WHERE address = ? AND source = ?", (address, only_source))
    return cur.rowcount > 0


# ── custom wallets (v15: added by hand, scored like the top 300, kept across refreshes) ──

def custom_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT address, added_ms FROM scout_custom ORDER BY added_ms").fetchall()]


def custom_addresses(conn: sqlite3.Connection) -> List[str]:
    return [r["address"] for r in custom_rows(conn)]


def add_custom(conn: sqlite3.Connection, address: str, now_ms: int) -> bool:
    """True when the wallet was not custom before."""
    with conn:
        cur = conn.execute("INSERT OR IGNORE INTO scout_custom (address, added_ms) VALUES (?, ?)", (address, now_ms))
    return cur.rowcount > 0


def remove_custom(conn: sqlite3.Connection, address: str) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM scout_custom WHERE address = ?", (address,))
    return cur.rowcount > 0


def drop_row(conn: sqlite3.Connection, refresh_id: str, address: str) -> bool:
    """Remove one wallet from a served build right away (a removed custom wallet must
    not wait for the next publish to leave the board)."""
    with conn:
        cur = conn.execute("DELETE FROM scout_rows WHERE refresh_id = ? AND address = ?", (refresh_id, address))
    return cur.rowcount > 0


def set_row_json(conn: sqlite3.Connection, refresh_id: str, address: str, row_json: str) -> None:
    with conn:
        conn.execute("UPDATE scout_rows SET row_json = ? WHERE refresh_id = ? AND address = ?",
                     (row_json, refresh_id, address))


def universe_row(conn: sqlite3.Connection, address: str) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_universe WHERE address = ?", (address,)).fetchone()
    return dict(r) if r else None


# ── departures (survivorship trail, user_consensus P1 #7) ───────────────────

DEPARTURE_RETENTION_MS = 180 * 24 * 60 * 60 * 1000   # keep 180d of history, then prune


def record_departures(conn: sqlite3.Connection, dropped: List[Dict[str, Any]], now_ms: int) -> None:
    """One row per wallet that just fell out of the ranked universe. Upsert:
    a wallet that leaves, comes back, and leaves again just gets its
    departed_ms refreshed, so the summary always reflects the latest exit."""
    if not dropped:
        return
    with conn:
        conn.executemany(
            "INSERT INTO scout_departures (address, display_name, last_account_value, last_pnl_30d, "
            "had_liquidation, last_seen_ms, departed_ms) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET display_name = excluded.display_name, "
            "last_account_value = excluded.last_account_value, last_pnl_30d = excluded.last_pnl_30d, "
            "had_liquidation = excluded.had_liquidation, last_seen_ms = excluded.last_seen_ms, "
            "departed_ms = excluded.departed_ms",
            [(d["address"], d.get("display_name"), d.get("account_value"), d.get("pnl_30d"),
              int(bool(d.get("had_liquidation"))), d.get("seen_ms"), now_ms) for d in dropped])
        conn.execute("DELETE FROM scout_departures WHERE departed_ms < ?", (now_ms - DEPARTURE_RETENTION_MS,))


def departures_summary(conn: sqlite3.Connection, since_ms: int) -> Dict[str, int]:
    r = conn.execute("SELECT COUNT(*), COALESCE(SUM(had_liquidation), 0) FROM scout_departures "
                     "WHERE departed_ms >= ?", (since_ms,)).fetchone()
    return {"departed": int(r[0] or 0), "departed_liquidated": int(r[1] or 0)}


# ── stats ─────────────────────────────────────────────────────────────────

def stats_row(conn: sqlite3.Connection, address: str) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_stats WHERE address = ?", (address,)).fetchone()
    return dict(r) if r else None


def stats_index(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """address -> {updated_ms, fail_count, skip_until_ms, last_try_ms}; no blobs."""
    rows = conn.execute("SELECT address, updated_ms, fail_count, skip_until_ms, last_try_ms FROM scout_stats")
    return {r["address"]: dict(r) for r in rows.fetchall()}


def save_stats(conn: sqlite3.Connection, address: str, now_ms: int, portfolio: Any, account: Any,
               positions: Any, stats: Any) -> None:
    with conn:
        conn.execute(
            "INSERT INTO scout_stats (address, updated_ms, portfolio_json, account_json, positions_json, "
            "positions_ms, stats_json, fail_count, skip_until_ms, last_try_ms, last_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, NULL) ON CONFLICT(address) DO UPDATE SET "
            "updated_ms = excluded.updated_ms, portfolio_json = excluded.portfolio_json, "
            "account_json = excluded.account_json, positions_json = excluded.positions_json, "
            "positions_ms = excluded.positions_ms, stats_json = excluded.stats_json, fail_count = 0, "
            "skip_until_ms = 0, last_try_ms = excluded.last_try_ms, last_error = NULL",
            (address, now_ms, json.dumps(portfolio), json.dumps(account), json.dumps(positions), now_ms,
             json.dumps(stats), now_ms))


def record_stats_failure(conn: sqlite3.Connection, address: str, now_ms: int, error: str,
                         skip_for_ms: int) -> int:
    """fail_count += 1; at FAILS_BEFORE_SKIP the wallet sits out one cycle.
    Old stats (if any) stay and keep serving, flagged stale by the row build."""
    with conn:
        conn.execute("INSERT INTO scout_stats (address, fail_count, last_try_ms, last_error) VALUES (?, 1, ?, ?) "
                     "ON CONFLICT(address) DO UPDATE SET fail_count = fail_count + 1, "
                     "last_try_ms = excluded.last_try_ms, last_error = excluded.last_error",
                     (address, now_ms, error[:500]))
        n = conn.execute("SELECT fail_count FROM scout_stats WHERE address = ?", (address,)).fetchone()[0]
        if n >= C.FAILS_BEFORE_SKIP:
            conn.execute("UPDATE scout_stats SET skip_until_ms = ? WHERE address = ?", (now_ms + skip_for_ms, address))
    return int(n)


# ── sim ───────────────────────────────────────────────────────────────────

def sim_row(conn: sqlite3.Connection, address: str, settings_hash: str, sim_equity: float) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_sim WHERE address = ? AND settings_hash = ? AND sim_equity = ?",
                     (address, settings_hash, sim_equity)).fetchone()
    return dict(r) if r else None


def sim_index(conn: sqlite3.Connection, settings_hash: str, sim_equity: float) -> Dict[str, int]:
    """address -> stats_ms the sim was computed from."""
    rows = conn.execute("SELECT address, stats_ms FROM scout_sim WHERE settings_hash = ? AND sim_equity = ?",
                        (settings_hash, sim_equity)).fetchall()
    return {r["address"]: int(r["stats_ms"] or 0) for r in rows}


def simmed_addresses(conn: sqlite3.Connection, addresses: Sequence[str]) -> set:
    """Which of `addresses` already have a sim row at ANY settings_hash/sim_equity.
    Their trip-span candles are already in the candle cache (prepare_wallet needs
    nothing new from the venue), so a re-sim of one of these at a NEW hash (a sim
    terms change) can run on CacheOnlyVenue: zero HL calls. A wallet with no prior
    sim at all (first build, or a brand new custom wallet) is never in this set,
    so it always gets a real venue the first time."""
    addrs = list(addresses)
    if not addrs:
        return set()
    rows = conn.execute(f"SELECT DISTINCT address FROM scout_sim WHERE address IN ({','.join('?' * len(addrs))})",
                        tuple(addrs)).fetchall()
    return {r["address"] for r in rows}


def save_sim(conn: sqlite3.Connection, address: str, settings_hash: str, sim_equity: float, now_ms: int,
             stats_ms: int, score: Dict[str, Any], curve: List[Dict[str, Any]]) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO scout_sim (address, settings_hash, sim_equity, updated_ms, stats_ms, "
                     "score_json, sim_curve_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (address, settings_hash, sim_equity, now_ms, stats_ms, json.dumps(score), json.dumps(curve)))


# ── rows + switchover ─────────────────────────────────────────────────────

def write_rows(conn: sqlite3.Connection, rows: Sequence[Dict[str, Any]]) -> None:
    """Rows for a NOT YET served refresh_id. Invisible to readers until switch()."""
    with conn:
        conn.executemany(f"INSERT OR REPLACE INTO scout_rows ({','.join(ROW_COLUMNS)}) "
                         f"VALUES ({','.join('?' * len(ROW_COLUMNS))})",
                         [tuple(r.get(c) for c in ROW_COLUMNS) for r in rows])


def switch(conn: sqlite3.Connection, refresh_id: str, settings_hash: str, as_of_ms: int, cohort: int,
           sim_equity: float = 0.0) -> None:
    """Point readers at refresh_id in one transaction, then prune to the last
    KEEP_REFRESHES builds (the one just replaced stays for in-flight readers)."""
    with conn:
        meta_set(conn, {"current_refresh": refresh_id, "current_hash": settings_hash,
                        "current_as_of": as_of_ms, "current_cohort": cohort, "current_equity": sim_equity},
                 commit=False)
        history = meta_get(conn, "refresh_history", [])
        history = [h for h in history if h != refresh_id] + [refresh_id]
        keep, drop = history[-C.KEEP_REFRESHES:], history[:-C.KEEP_REFRESHES]
        meta_set(conn, {"refresh_history": keep}, commit=False)
        for rid in drop:
            conn.execute("DELETE FROM scout_rows WHERE refresh_id = ?", (rid,))
        # rows of builds that never got switched to (crashed mid-write) are garbage too
        conn.execute(f"DELETE FROM scout_rows WHERE refresh_id NOT IN ({','.join('?' * len(keep))})", tuple(keep))


def row_json(conn: sqlite3.Connection, refresh_id: str, address: str) -> Optional[str]:
    r = conn.execute("SELECT row_json FROM scout_rows WHERE refresh_id = ? AND address = ?",
                     (refresh_id, address)).fetchone()
    return r["row_json"] if r else None


# ── refresh runs ──────────────────────────────────────────────────────────

def try_begin_refresh(conn: sqlite3.Connection, refresh_id: str, now_ms: int, kind: str) -> Optional[Dict[str, Any]]:
    """Atomically claim the single refresh slot (BEGIN IMMEDIATE: one writer
    across every process). A `running` row whose heartbeat is older than
    REFRESH_STALE_S is a dead process: marked failed, slot taken. Returns
    the blocking run's row, or None when the claim succeeded."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        r = conn.execute("SELECT * FROM scout_refresh WHERE state = 'running' ORDER BY started_ms DESC LIMIT 1").fetchone()
        if r is not None:
            if now_ms - int(r["heartbeat_ms"] or r["started_ms"] or 0) <= C.REFRESH_STALE_S * 1000:
                conn.execute("ROLLBACK")
                return dict(r)
            conn.execute("UPDATE scout_refresh SET state = 'failed', finished_ms = ?, error = ? WHERE refresh_id = ?",
                         (now_ms, "no heartbeat: process died", r["refresh_id"]))
        conn.execute("INSERT INTO scout_refresh (refresh_id, started_ms, heartbeat_ms, state, stage, done, total, kind) "
                     "VALUES (?, ?, ?, 'running', 'leaderboard', 0, 0, ?)", (refresh_id, now_ms, now_ms, kind))
        conn.execute("COMMIT")
        return None
    except Exception:
        conn.execute("ROLLBACK")
        raise


def update_refresh(conn: sqlite3.Connection, refresh_id: str, **fields: Any) -> None:
    if not fields:
        return
    with conn:
        conn.execute(f"UPDATE scout_refresh SET {', '.join(f'{k} = ?' for k in fields)} WHERE refresh_id = ?",
                     (*fields.values(), refresh_id))


def latest_refresh(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_refresh ORDER BY started_ms DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def last_ok_ms(conn: sqlite3.Connection) -> Optional[int]:
    r = conn.execute("SELECT MAX(finished_ms) FROM scout_refresh WHERE state = 'done'").fetchone()
    return int(r[0]) if r and r[0] is not None else None


# ── on-demand requests ────────────────────────────────────────────────────

def request_build(conn: sqlite3.Connection, address: str, now_ms: int) -> None:
    with conn:
        conn.execute("INSERT INTO scout_requests (address, requested_ms) VALUES (?, ?) "
                     "ON CONFLICT(address) DO NOTHING", (address, now_ms))


def request_row(conn: sqlite3.Connection, address: str) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT * FROM scout_requests WHERE address = ?", (address,)).fetchone()
    return dict(r) if r else None


def pending_requests(conn: sqlite3.Connection, max_attempts: int) -> List[str]:
    rows = conn.execute("SELECT address FROM scout_requests WHERE attempts < ? ORDER BY requested_ms",
                        (max_attempts,)).fetchall()
    return [r["address"] for r in rows]


def finish_request(conn: sqlite3.Connection, address: str, error: Optional[str]) -> None:
    with conn:
        if error is None:
            conn.execute("DELETE FROM scout_requests WHERE address = ?", (address,))
        else:
            conn.execute("UPDATE scout_requests SET attempts = attempts + 1, last_error = ? WHERE address = ?",
                         (error[:500], address))
