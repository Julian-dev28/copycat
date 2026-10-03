"""Settings file I/O: re-read `$COPYCAT_DATA_DIR/settings.json` every cycle.

`services/api` is the only writer (atomic tmp + os.replace, per
docs/ARCHITECTURE.md); the engine only ever reads. On a missing or invalid
file, the engine keeps the last settings that DID parse rather than halting
or falling back to bare defaults mid-run -- a half-written file during an
api restart, or a momentary bad edit, must never make the engine forget it
was running with real leaders configured. The last-good copy is persisted in
SQLite (`kv["last_good_settings"]`), not held in a module global, so it
survives an engine restart too.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple, Union

from pydantic import ValidationError

from contracts.models import Settings

from .state import EngineState

_KV_KEY = "last_good_settings"


def load_settings(path: Union[str, Path], state: EngineState) -> Tuple[Settings, Optional[str]]:
    """Read and validate `path` as a `Settings` JSON file.

    Returns `(settings, error)`:
      - Valid file: `(parsed Settings, None)`. The SQLite last-good copy is
        refreshed.
      - Missing or invalid file, with a previous good copy in SQLite:
        `(that last-good Settings, "<human-readable reason>")`.
      - Missing file, no previous good copy yet (first boot, before the api
        has ever written settings.json -- the normal pre-setup state):
        `(Settings(), None)`. Not an error: there is nothing wrong, nobody
        has configured anything yet, and `Settings()` defaults ship
        `enabled=False, dry_run=True` -- safe to sit on.
      - Invalid (malformed JSON / fails validation) file, no previous good
        copy: `(Settings(), "<reason>")`. Unlike a missing file, a file that
        EXISTS but is broken is always worth surfacing, even on first boot.
    """
    path = Path(path)
    last_good_raw = state.get_kv(_KV_KEY)
    last_good = Settings.model_validate(last_good_raw) if last_good_raw is not None else None

    if not path.exists():
        if last_good is not None:
            return last_good, "settings.json is missing, keeping last known-good settings"
        return Settings(), None

    try:
        data = json.loads(path.read_text())
        settings = Settings.model_validate(data)
    except (json.JSONDecodeError, ValidationError, OSError, UnicodeDecodeError) as exc:
        reason = f"settings.json is invalid ({exc})"
        if last_good is not None:
            return last_good, f"{reason}, keeping last known-good settings"
        return Settings(), f"{reason}, using safe defaults"

    state.set_kv(_KV_KEY, settings.model_dump(mode="json"))
    return settings, None
