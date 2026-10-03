"""Discovery's own config: where its sqlite db lives, and the defaults for
a run that aren't part of the user-editable `Settings` contract (those are
candidate-pull filters, not sizing/leverage rules)."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("COPYCAT_DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "discovery.db"

DEFAULT_TOP_N = 50
DEFAULT_WINDOW_DAYS = 30
DEFAULT_MIN_ACCOUNT_VALUE_USD = 10_000.0
DEFAULT_MIN_VOLUME_30D_USD = 50_000.0
