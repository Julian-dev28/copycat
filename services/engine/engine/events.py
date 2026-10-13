"""The engine's append-only event log: `$COPYCAT_DATA_DIR/events.jsonl`, one
`EngineEvent` per line. Append-only by design -- `services/api` tails/streams
it, so rewriting history under a concurrent reader would be wrong, not just
inconvenient.

Actions: baseline, open, add, reduce, close, intent, error, halt, resume,
and `skip`. A skip is logged only when a coin's (or leader's) skip reason
first appears or changes (`core._log_skip_changes`), never every cycle, and
carries the leader it belongs to, so one wallet's history
(`read_leader_events`) shows why its moves were not copied.

Growth control: `events.jsonl` still grows forever from the actions that DO
get logged. Past `_MAX_BYTES` the file is rotated to a single `.jsonl.1`
backup on the next append (not merged back in by `read_events` -- read the
backup file directly if you need older history). This is a deliberately
simple one-generation rotation, not a log database; it exists so a
long-running self-hosted instance cannot fill its disk unattended.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Union

from contracts.models import EngineEvent

logger = logging.getLogger(__name__)

_MAX_BYTES = 25_000_000  # ~25MB before a one-generation rotation


def append_event(path: Union[str, Path], event: EngineEvent) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_large(path)
    with open(path, "a") as fh:
        fh.write(event.model_dump_json() + "\n")


def _rotate_if_large(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            os.replace(path, path.with_suffix(path.suffix + ".1"))
    except OSError:
        logger.warning("events.jsonl rotation failed, continuing without it", exc_info=True)


def for_account(ev: EngineEvent, account: Optional[str]) -> bool:
    """Audit M10: an event belongs on `account`'s feed when it was written for
    that account or for no account in particular (pre-v12 lines, engine-wide
    errors). `account` None shows everything."""
    return account is None or ev.account is None or ev.account.lower() == account.lower()


def read_events(path: Union[str, Path], limit: int = 100,
                 since_ms: Optional[int] = None,
                 account: Optional[str] = None) -> List[EngineEvent]:
    """Newest first, at most `limit`, optionally only events with
    `ts_ms > since_ms`. Only reads the live file (see module docstring on
    rotation) -- a missing file returns an empty list, never an error: no
    events have happened yet is not a failure.
    """
    path = Path(path)
    if not path.exists():
        return []
    out: List[EngineEvent] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                ev = EngineEvent.model_validate(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("unparseable events.jsonl line skipped: %s", exc)
                continue
            if since_ms is not None and ev.ts_ms <= since_ms:
                continue
            if not for_account(ev, account):
                continue
            out.append(ev)
    out.sort(key=lambda e: e.ts_ms, reverse=True)
    return out[:limit]


_TAIL_BLOCK = 64 * 1024
MAX_SCAN_BYTES = 8 * 1024 * 1024   # a wallet's history page never reads more than this


def read_leader_events(path: Union[str, Path], leader: str, limit: int = 50,
                       before_ms: Optional[int] = None,
                       max_scan_bytes: int = MAX_SCAN_BYTES,
                       account: Optional[str] = None) -> List[EngineEvent]:
    """One wallet's events (actions and skips with reasons), newest first:
    `event.leader == leader` and, with `before_ms`, `ts_ms < before_ms`
    (page with the last row's ts_ms). Reads the live file backwards from the
    end in 64KB blocks and stops at `limit` matches or `max_scan_bytes`
    scanned, so a 25MB log costs at most 8MB of reading, never a full parse.
    Lines are appended in time order, so the backwards walk is newest first;
    lines that do not parse are skipped. A missing file is an empty list."""
    path = Path(path)
    leader = leader.lower()
    if limit <= 0 or not path.exists():
        return []
    out: List[EngineEvent] = []
    needle = leader.encode()   # cheap prefilter; _match parses and checks the field
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        scanned = 0
        tail = b""
        while pos > 0 and scanned < max_scan_bytes and len(out) < limit:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + tail
            scanned += step
            lines = buf.split(b"\n")
            # the first piece may be a partial line unless we reached the file start
            tail = lines.pop(0) if pos > 0 else b""
            for raw in reversed(lines):
                ev = _match(raw, needle, leader, before_ms)
                if ev is not None and for_account(ev, account):
                    out.append(ev)
                    if len(out) >= limit:
                        break
    return out[:limit]


def _match(raw: bytes, needle: bytes, leader: str, before_ms: Optional[int]) -> Optional[EngineEvent]:
    raw = raw.strip()
    if not raw or needle not in raw.lower():
        return None
    try:
        ev = EngineEvent.model_validate_json(raw)
    except ValueError:
        return None
    if (ev.leader or "").lower() != leader:
        return None
    if before_ms is not None and ev.ts_ms >= before_ms:
        return None
    return ev
