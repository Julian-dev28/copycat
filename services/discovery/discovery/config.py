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

# A re-run within this many seconds of a wallet's/coin's last fetch skips
# the tail fetch (window effectively ends up to this stale). Makes warm runs
# cheap; 0 disables.
CACHE_FRESH_S = float(os.environ.get("COPYCAT_DISCOVERY_FRESH_S", "900"))
LEADERBOARD_TTL_S = float(os.environ.get("COPYCAT_DISCOVERY_LEADERBOARD_TTL_S", "900"))
# A `running` row whose heartbeat is older than this is a dead worker: marked
# failed so it stops blocking new runs.
STALE_RUN_S = float(os.environ.get("COPYCAT_DISCOVERY_STALE_RUN_S", "600"))
