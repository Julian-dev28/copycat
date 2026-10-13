"""Passphrase guessing guard (audit M6).

Every route that unlocks a created wallet's main key (refresh-agent,
transfer, withdraw / send / move) goes through `manage._unlock_main`, so the
guard sits there, per account, shared by all of them, and persisted under
data/vault/ so a restart does not reset it.

Policy: the first FREE_FAILS wrong passphrases cost nothing extra (typos).
After that each further failure locks the account's unlock for
2^(fails - FREE_FAILS) minutes, capped at MAX_LOCK_S. A correct passphrase
clears the count. While locked, the passphrase is not even tried (no scrypt,
no oracle), and the error says how long to wait.

Combined with scrypt N=2^17 this makes online guessing hopeless: after 10
failures the next try is 2^7 = 128 min away, after 15 a full day.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator

from . import fsio
from .errors import VaultError

GUARD_FILE = "passphrase_guard.json"
FREE_FAILS = 3
MAX_LOCK_S = 24 * 3600


class TooManyGuesses(VaultError):
    http_status = 429


def _path():
    return fsio.vault_dir() / GUARD_FILE


def _load() -> Dict[str, Any]:
    p = _path()
    if not p.exists():
        return {}
    try:
        doc = json.loads(fsio.read_private(p) or b"{}")
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _save(doc: Dict[str, Any]) -> None:
    fsio.ensure_dir(fsio.vault_dir())
    fsio.atomic_write(_path(), json.dumps(doc, sort_keys=True).encode())


@contextmanager
def _guard_lock() -> Iterator[None]:
    """Its own lock file: callers may already hold fsio.locked() (flock is per
    open file, so taking that one again from this process would deadlock)."""
    d = fsio.ensure_dir(fsio.vault_dir())
    fd = os.open(d / ".guard.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def lock_seconds(fails: int) -> int:
    if fails <= FREE_FAILS:
        return 0
    return int(min(MAX_LOCK_S, 60 * 2 ** (fails - FREE_FAILS - 1)))


def check(account_id: str, clock: Callable[[], float] = time.time) -> None:
    """Raise TooManyGuesses while the account's unlock is locked."""
    row = _load().get(account_id) or {}
    wait = float(row.get("until") or 0) - clock()
    if wait > 0:
        mins = math.ceil(wait / 60)
        raise TooManyGuesses(f"too many wrong passphrases for this account: try again in {mins} min")


def failed(account_id: str, clock: Callable[[], float] = time.time) -> None:
    with _guard_lock():
        doc = _load()
        row = doc.get(account_id) or {}
        fails = int(row.get("fails") or 0) + 1
        doc[account_id] = {"fails": fails, "until": clock() + lock_seconds(fails)}
        _save(doc)


def succeeded(account_id: str) -> None:
    with _guard_lock():
        doc = _load()
        if account_id in doc:
            del doc[account_id]
            _save(doc)
