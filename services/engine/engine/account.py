"""Which account the engine trades, and where that account's state lives.

Resolution, every cycle (same rule as hl.env, so the address we read and the
key hl signs with always agree):
  1. the vault (`vault.public`), once it is authoritative (an account was
     activated at least once): its active account, or none.
  2. otherwise COPYCAT_ACCOUNT_ADDRESS.

State is per account: `engine-<address>.db`. Copies opened under account A are
only ever managed while A is active; switching to B starts B from a clean book.
A pre-v6 `engine.db` is adopted (renamed) by the account it belongs to.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LEGACY_DB = "engine.db"


def _data_dir() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data"))


def vault_decides() -> bool:
    if not (_data_dir() / "vault" / "accounts.json").exists():
        return False
    try:
        from vault import public  # type: ignore[import-not-found]
        return bool(public.is_authoritative())
    except Exception as exc:
        logger.error("vault present but unreadable (%s): trading no account", type(exc).__name__)
        return True


def resolve_our_address() -> str:
    """The active main account, lowercase, or "" when none."""
    if vault_decides():
        try:
            from vault import public  # type: ignore[import-not-found]
            return (public.active_address() or "").lower()
        except Exception as exc:
            logger.error("vault active account unreadable (%s)", type(exc).__name__)
            return ""
    return (os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip().lower()


def db_path(address: str) -> Path:
    return _data_dir() / f"engine-{address.lower()}.db"


def _legacy_owner(path: Path) -> Optional[str]:
    """our_address recorded in the legacy db's last status snapshot."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM kv WHERE key = 'last_status'").fetchone()
        finally:
            conn.close()
        return ((json.loads(row[0]).get("status") or {}).get("our_address") or "").lower() or None if row else None
    except Exception:
        return None


def adopt_legacy_db(address: str) -> bool:
    """Rename a pre-v6 engine.db to engine-<address>.db when it belongs to this
    address (its last snapshot says so, or it never recorded one and the
    address is COPYCAT_ACCOUNT_ADDRESS). Never overwrites an existing db."""
    legacy, target = _data_dir() / LEGACY_DB, db_path(address)
    if not legacy.exists() or target.exists():
        return False
    owner = _legacy_owner(legacy)
    env_addr = (os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip().lower()
    if owner != address.lower() and not (owner is None and env_addr == address.lower()):
        return False
    conn = sqlite3.connect(legacy)          # fold the WAL into the main file before moving it
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    legacy.rename(target)
    for suffix in ("-wal", "-shm"):
        side = legacy.with_name(LEGACY_DB + suffix)
        if side.exists():
            side.unlink()
    logger.info("adopted legacy %s as %s", legacy, target.name)
    return True
