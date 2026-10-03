"""The emergency close-all request: `data/close_all.flag`.

The api writes the flag (atomic tmp + os.replace, same as settings.json);
the engine worker reads it at the start of its next cycle, closes every
row in its own `copies` table reduce-only, and deletes the flag once none
remain (a failed close keeps it, so the next cycle retries). The file name
is part of the contract in docs/ARCHITECTURE.md; the api never imports the
engine to learn it. Contents are informational JSON ({requested_ms}); the
engine only checks that the file exists.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

FLAG_NAME = "close_all.flag"


def flag_path(data_dir: Path) -> Path:
    return Path(data_dir) / FLAG_NAME


def request_close_all(data_dir: Path, requested_ms: int) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".close_all-", suffix=".tmp", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"requested_ms": requested_ms}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, flag_path(data_dir))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_pending(data_dir: Path) -> bool:
    return flag_path(data_dir).exists()
