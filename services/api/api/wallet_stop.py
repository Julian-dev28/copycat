"""Stop-one-wallet requests: `data/stop/<address>.flag`.

The api writes the flag (atomic tmp + os.replace, like close_all.flag),
JSON {close_positions, requested_ms}; the engine reads every flag at the
start of its next cycle (`engine.public.read_stops`), treats that leader as
an orphan, closes his copies reduce-only when close_positions is true
(retrying each cycle until flat) and deletes the flag when done. The dir
and file names are the contract in docs/ARCHITECTURE.md; the api never
imports the engine to learn them.

Re-investing in a wallet (POST /api/wallets/{address}/copy) deletes its
pending flag: the newer command wins.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STOP_DIR = "stop"


def stop_path(data_dir: Path, address: str) -> Path:
    return Path(data_dir) / STOP_DIR / f"{address}.flag"


def request_stop(data_dir: Path, address: str, close_positions: bool, requested_ms: int) -> None:
    d = Path(data_dir) / STOP_DIR
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".stop-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"close_positions": close_positions, "requested_ms": requested_ms}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, stop_path(data_dir, address))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clear_stop(data_dir: Path, address: str) -> bool:
    """Delete a pending stop. True if there was one."""
    try:
        stop_path(data_dir, address).unlink()
        return True
    except FileNotFoundError:
        return False


def is_stop_pending(data_dir: Path, address: str) -> bool:
    return stop_path(data_dir, address).exists()
