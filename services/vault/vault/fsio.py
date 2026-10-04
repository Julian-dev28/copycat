"""Vault filesystem: $COPYCAT_DATA_DIR/vault, dir 0700, files 0600, atomic writes.

Atomic write = temp file in the same dir (created 0600 by mkstemp) + fsync +
os.replace + fsync of the directory, so a crash leaves the old file or the new
one, never half of either. Mutations run under an flock on vault/.lock so the
api's threads and processes never lose an update.
"""
from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DIR_MODE = 0o700
FILE_MODE = 0o600


def data_dir() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR") or "./data")


def vault_dir() -> Path:
    return data_dir() / "vault"


def ensure_dir(path: Path) -> Path:
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    if (path.stat().st_mode & 0o777) != DIR_MODE:
        os.chmod(path, DIR_MODE)
    return path


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def create_exclusive(path: Path, data: bytes) -> bool:
    """Write `path` only if it does not exist (atomic, 0600). False if another
    writer got there first. Used for the machine key: two processes starting
    together must end up with ONE key."""
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        _fsync_dir(path.parent)
        return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read_private(path: Path) -> bytes:
    """Read a vault file, tightening its mode to 0600 if something loosened it."""
    if (path.stat().st_mode & 0o777) != FILE_MODE:
        os.chmod(path, FILE_MODE)
    return path.read_bytes()


@contextmanager
def locked() -> Iterator[None]:
    d = ensure_dir(vault_dir())
    fd = os.open(d / ".lock", os.O_RDWR | os.O_CREAT, FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
