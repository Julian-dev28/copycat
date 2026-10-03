"""SQLite-backed engine state: stdlib `sqlite3`, WAL mode, one file at
`$COPYCAT_DATA_DIR/engine.db`. No ORM -- the schema is four small tables and
every access goes through this module, so `core.py` never writes raw SQL and
two processes (the engine worker writing, the api reading `status()`) can
open their own connection to the same file safely. WAL mode is what makes
that cross-process read-while-write pattern safe; `check_same_thread=False`
only relaxes sqlite3's own single-thread guard, which is irrelevant here
since each process opens its own connection.

Tables:
  leaders     one row per leader we have ever read: his last-seen positions
              (coin -> signed size) and his "ignored" coin set, the exact
              state `core.py`'s diff loop needs to pick up where it left off
              every cycle. A leader removed from `Settings.leaders` keeps
              its row (it becomes an "orphan": exits still mirror, see
              `core.py`) until nothing references it any more; rows are
              never pruned automatically.
  copies      one row per coin WE actually hold a real position in, opened
              by this engine. The source of truth for "which leader owns
              this coin" and for `EngineStatus.positions`. Never touched
              while `Settings.dry_run` is true.
  dry_copies  the dry-run shadow of `copies` -- same shape plus a simulated
              `size`, since there is no real exchange position to read size
              from. Exists purely so a SEQUENCE of dry-run cycles classifies
              open/add/reduce/close correctly for the `intent` events it
              emits. Never read by the real (non-dry) decision path and
              never surfaced in `EngineStatus.positions` -- a dry position
              is not a real one and must never be mistaken for one.
  kv          small singleton values as JSON text: `last_good_settings` (the
              last `Settings` that parsed, for `settings_io.py`'s fallback),
              `last_status` (the most recent `EngineStatus` snapshot, so
              `public.status()` can answer from a fresh process with no
              venue), `day_anchor` (today's UTC day key + the equity it
              started at, for the daily-loss gate), `halted` (bool, to emit
              halt/resume events only on the transition).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaders (
    address TEXT PRIMARY KEY,
    last_positions TEXT NOT NULL DEFAULT '{}',
    ignored TEXT NOT NULL DEFAULT '[]',
    last_read_ms INTEGER
);
CREATE TABLE IF NOT EXISTS copies (
    coin TEXT PRIMARY KEY,
    leader TEXT NOT NULL,
    opened_ms INTEGER NOT NULL,
    leverage INTEGER NOT NULL,
    is_cross INTEGER NOT NULL,
    sizing_mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dry_copies (
    coin TEXT PRIMARY KEY,
    leader TEXT NOT NULL,
    opened_ms INTEGER NOT NULL,
    leverage INTEGER NOT NULL,
    is_cross INTEGER NOT NULL,
    sizing_mode TEXT NOT NULL,
    size REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class LeaderState:
    __slots__ = ("address", "last_positions", "ignored", "last_read_ms")

    def __init__(self, address: str, last_positions: Dict[str, float], ignored: List[str],
                 last_read_ms: Optional[int] = None):
        self.address = address
        self.last_positions = last_positions
        self.ignored = ignored
        self.last_read_ms = last_read_ms


class Copy:
    """A real (or, as `DryCopy`, simulated) position this engine opened."""
    __slots__ = ("coin", "leader", "opened_ms", "leverage", "is_cross", "sizing_mode")

    def __init__(self, coin: str, leader: str, opened_ms: int, leverage: int,
                 is_cross: bool, sizing_mode: str):
        self.coin = coin
        self.leader = leader
        self.opened_ms = opened_ms
        self.leverage = leverage
        self.is_cross = is_cross
        self.sizing_mode = sizing_mode


class DryCopy(Copy):
    """`Copy` plus a simulated signed size -- dry-run has no real exchange
    position to read a size back from, so it has to track its own."""
    __slots__ = ("size",)

    def __init__(self, coin: str, leader: str, opened_ms: int, leverage: int,
                 is_cross: bool, sizing_mode: str, size: float):
        super().__init__(coin, leader, opened_ms, leverage, is_cross, sizing_mode)
        self.size = size


class EngineState:
    """One sqlite3 connection per instance. Callers own the lifecycle: use as
    a context manager or call `.close()` explicitly."""

    def __init__(self, path: Union[str, "Path"]):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EngineState":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── leaders ──────────────────────────────────────────────────────────

    def get_leader(self, address: str) -> Optional[LeaderState]:
        row = self._conn.execute(
            "SELECT address, last_positions, ignored, last_read_ms FROM leaders WHERE address = ?",
            (address,)).fetchone()
        if row is None:
            return None
        return LeaderState(row[0], json.loads(row[1]), json.loads(row[2]), row[3])

    def put_leader(self, ls: LeaderState) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO leaders (address, last_positions, ignored, last_read_ms) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(address) DO UPDATE SET "
                "last_positions = excluded.last_positions, ignored = excluded.ignored, "
                "last_read_ms = excluded.last_read_ms",
                (ls.address, json.dumps(ls.last_positions), json.dumps(sorted(ls.ignored)),
                 ls.last_read_ms))
            self._conn.commit()

    def leader_addresses(self) -> List[str]:
        return [r[0] for r in self._conn.execute("SELECT address FROM leaders").fetchall()]

    # ── copies (real) ────────────────────────────────────────────────────

    def get_copy(self, coin: str) -> Optional[Copy]:
        row = self._conn.execute(
            "SELECT coin, leader, opened_ms, leverage, is_cross, sizing_mode "
            "FROM copies WHERE coin = ?", (coin,)).fetchone()
        return self._row_to_copy(row) if row else None

    def put_copy(self, c: Copy) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO copies (coin, leader, opened_ms, leverage, is_cross, sizing_mode) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(coin) DO UPDATE SET "
                "leader = excluded.leader, opened_ms = excluded.opened_ms, "
                "leverage = excluded.leverage, is_cross = excluded.is_cross, "
                "sizing_mode = excluded.sizing_mode",
                (c.coin, c.leader, c.opened_ms, c.leverage, int(c.is_cross), c.sizing_mode))
            self._conn.commit()

    def delete_copy(self, coin: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM copies WHERE coin = ?", (coin,))
            self._conn.commit()

    def all_copies(self) -> List[Copy]:
        rows = self._conn.execute(
            "SELECT coin, leader, opened_ms, leverage, is_cross, sizing_mode FROM copies").fetchall()
        return [self._row_to_copy(r) for r in rows]

    @staticmethod
    def _row_to_copy(row: Any) -> Copy:
        return Copy(row[0], row[1], row[2], row[3], bool(row[4]), row[5])

    # ── dry_copies (shadow) ──────────────────────────────────────────────

    def get_dry_copy(self, coin: str) -> Optional[DryCopy]:
        row = self._conn.execute(
            "SELECT coin, leader, opened_ms, leverage, is_cross, sizing_mode, size "
            "FROM dry_copies WHERE coin = ?", (coin,)).fetchone()
        return self._row_to_dry_copy(row) if row else None

    def put_dry_copy(self, c: DryCopy) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO dry_copies "
                "(coin, leader, opened_ms, leverage, is_cross, sizing_mode, size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(coin) DO UPDATE SET "
                "leader = excluded.leader, opened_ms = excluded.opened_ms, "
                "leverage = excluded.leverage, is_cross = excluded.is_cross, "
                "sizing_mode = excluded.sizing_mode, size = excluded.size",
                (c.coin, c.leader, c.opened_ms, c.leverage, int(c.is_cross), c.sizing_mode, c.size))
            self._conn.commit()

    def delete_dry_copy(self, coin: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM dry_copies WHERE coin = ?", (coin,))
            self._conn.commit()

    def all_dry_copies(self) -> List[DryCopy]:
        rows = self._conn.execute(
            "SELECT coin, leader, opened_ms, leverage, is_cross, sizing_mode, size "
            "FROM dry_copies").fetchall()
        return [self._row_to_dry_copy(r) for r in rows]

    @staticmethod
    def _row_to_dry_copy(row: Any) -> DryCopy:
        return DryCopy(row[0], row[1], row[2], row[3], bool(row[4]), row[5], row[6])

    # ── kv ───────────────────────────────────────────────────────────────

    def get_kv(self, key: str) -> Optional[Any]:
        row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_kv(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)))
            self._conn.commit()
