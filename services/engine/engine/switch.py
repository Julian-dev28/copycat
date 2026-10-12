"""Active-account bookkeeping for engine.public.

  engine_account.json  {"address": "0x..." | "", "since_ms"}: the account the
                       last cycle traded. A change is logged as an event.
  engine_status.json   the last cycle's EngineStatus snapshot, whatever account
                       (or none) it ran for. engine.public.status() reads it.
Both written atomically (tmp + os.replace).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from contracts.models import EngineEvent

from . import account as acct_mod
from .state import EngineState

ACCOUNT_FILE = "engine_account.json"
STATUS_FILE = "engine_status.json"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def open_copies(address: str) -> int:
    path = acct_mod.db_path(address)
    if not address or not path.exists():
        return 0
    with EngineState(path) as st:
        return len(st.all_copies())


def note_account(data_dir: Path, address: str, now_ms: int,
                 log_event: Callable[[EngineEvent], None]) -> Optional[str]:
    """Record the account this cycle runs for. Returns the previous one when it
    changed (None otherwise) after logging the switch."""
    path = data_dir / ACCOUNT_FILE
    prev_doc = _read_json(path)
    prev = (prev_doc or {}).get("address")
    if prev_doc is not None and prev == address:
        return None
    _write_json(path, {"address": address, "since_ms": now_ms})
    if prev_doc is None:
        return None                      # first run: nothing switched
    left = open_copies(prev) if prev else 0
    if not address:
        reason = f"no active trading account: nothing is traded (was {prev or 'none'})"
    else:
        reason = f"active trading account changed {prev or 'none'} -> {address}; new account starts a clean book"
    if left:
        reason += f". {left} copies of {prev} are no longer managed: activate it again to manage or close them"
    log_event(EngineEvent(ts_ms=now_ms, action="error" if left or not address else "intent", reason=reason))
    return prev or ""


def write_status(data_dir: Path, status: Dict[str, Any], poll_interval_s: float,
                 build: Optional[Dict[str, Any]] = None) -> None:
    """`build`: this engine process's contracts.build info (version-skew guard:
    GET /api/health shows it next to the api's own build)."""
    body: Dict[str, Any] = {"status": status, "poll_interval_s": poll_interval_s}
    if build is not None:
        body["build"] = build
    _write_json(data_dir / STATUS_FILE, body)


def read_status(data_dir: Path) -> Optional[Dict[str, Any]]:
    return _read_json(data_dir / STATUS_FILE)
