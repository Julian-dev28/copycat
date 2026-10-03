"""Every threshold the thesis engine uses, in one place. README.md in this
directory documents each one; a tuning change is one diff here plus the
matching README line."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

DEFAULT_WINDOW_DAYS = 30


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def db_path() -> Path:
    """data/discovery.db, read at call time so COPYCAT_DATA_DIR set after
    import (tests, the api's child process) is honoured. Same WAL file as
    the fills and candle caches the fingerprint reads."""
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data")) / "discovery.db"


# ── cache ────────────────────────────────────────────────────────────────
FINGERPRINT_TTL_S = _f("COPYCAT_THESIS_TTL_S", 3600.0)   # a stored fingerprint younger than this is reused
FILLS_FRESH_S = _f("COPYCAT_DISCOVERY_FRESH_S", 900.0)    # same knob as discovery.config.CACHE_FRESH_S

# ── candles / indicators ─────────────────────────────────────────────────
CANDLE_INTERVAL = "1h"
CANDLE_STEP_MS = HOUR_MS
HL_MAX_BARS = 5000                     # HL serves the newest ~5000 bars per interval: 1h reaches ~208 days
WARMUP_BARS = 200                      # bars before each entry fed to EMA/RSI (EMA50 seed error < 0.3% after 150)
EMA_PERIOD = 50
EMA_SLOPE_BARS = 5                     # slope = EMA50[last] - EMA50[last - 5]
RSI_PERIOD = 14
RANGE_BARS = 20                        # 20-bar high / low
BREAKOUT_TOL_PCT = 0.5                 # long within 0.5% of the 20-bar high (short: of the low)
PULLBACK_MIN_PCT = 2.0                 # long >= 2% under the 20-bar high and above EMA50 (mirror for shorts)
MAX_BAR_STALENESS_MS = 3 * HOUR_MS     # last closed bar must end within 3h of the entry, else no context

# ── trips ────────────────────────────────────────────────────────────────
ACTION_MERGE_MS = 60_000               # same-direction fills within 60s are one action (one add, one exit)

# ── sample sizes ─────────────────────────────────────────────────────────
MIN_TRIPS_FOR_TAGS = 5                 # below this, no tags at all
MIN_CONTEXT_FOR_ENTRY_TAGS = 5         # candle-based tags need this many trips with context
SMALL_SAMPLE_TRIPS = 20                # below this, a "sketch, not a pattern" caveat
ALGO_CAVEAT_OPENS_PER_DAY = 100.0
FILLS_CAP = 10_000                     # userFillsByTime serves only the newest 10k fills
TRUNCATED_MIN_FILLS = 9_000

# ── timing ───────────────────────────────────────────────────────────────
SESSION_HOURS = 6                      # session trader: >= SESSION_MIN_PCT of entries in one 6h UTC window

# ── tags: (tag, metric, op, threshold). Evaluated in this order. ─────────
# metric names are StrategyFingerprint fields plus "session_pct" (best 6h window share).
TAG_RULES: List[Tuple[str, str, str, float]] = [
    ("trend follower",   "trend_aligned_pct",      ">=", 65.0),
    ("counter-trend",    "trend_aligned_pct",      "<=", 35.0),
    ("dip buyer",        "pullback_pct",           ">=", 40.0),
    ("breakout buyer",   "breakout_pct",           ">=", 40.0),
    ("scales in",        "scales_in_pct",          ">=", 50.0),
    ("scales out",       "scales_out_pct",         ">=", 50.0),
    ("runs winners",     "payoff_ratio",           ">=", 2.0),
    ("cuts losers fast", "loser_hold_vs_winner",   "<",  0.5),
    ("holds losers",     "loser_hold_vs_winner",   ">=", 2.0),
    ("high win rate",    "win_rate_pct",           ">=", 65.0),
    ("high leverage",    "avg_leverage",           ">=", 10.0),
    ("concentrated",     "pnl_from_top_coin_pct",  ">=", 60.0),
    ("session trader",   "session_pct",            ">=", 50.0),
    ("long biased",      "long_pct",               ">=", 75.0),
    ("short biased",     "long_pct",               "<=", 25.0),
]
CANDLE_METRICS = {"trend_aligned_pct", "pullback_pct", "breakout_pct"}

MAX_EXAMPLES = 8
MAX_SUMMARY_SENTENCES = 8
TOP_COINS = 5
