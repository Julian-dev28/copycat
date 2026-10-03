"""The engine's append-only event log: `$COPYCAT_DATA_DIR/events.jsonl`, one
`EngineEvent` per line. Append-only by design -- `services/api` tails/streams
it, so rewriting history under a concurrent reader would be wrong, not just
inconvenient.

Only a few actions are ever logged here (baseline, open, add, reduce, close,
intent, error, halt, resume) -- the same set `pathiel`'s copycat_live logged
through its `log_event` callback. Routine per-cycle skip reasons do NOT go
here; they are cycle-local and only ever visible in the one-line cycle log
and `run_cycle()`'s return value. Logging every "owned by leader X" or
"entries blocked" skip to a permanent file would make it grow unboundedly
fast for no operational benefit.

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


def read_events(path: Union[str, Path], limit: int = 100,
                 since_ms: Optional[int] = None) -> List[EngineEvent]:
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
            out.append(ev)
    out.sort(key=lambda e: e.ts_ms, reverse=True)
    return out[:limit]
