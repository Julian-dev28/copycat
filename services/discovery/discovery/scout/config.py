"""Scout constants. Every threshold the spec names lives here, so a test
can point at one place and a tuning change is one diff."""
from __future__ import annotations

import os
from pathlib import Path


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def db_path() -> Path:
    """Same WAL file as the rest of discovery (data/discovery.db), so stage B
    and C share the fills and candle caches with manual /discover runs."""
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data")) / "discovery.db"


def progress_log_path() -> Path:
    return Path(os.environ.get("COPYCAT_SCOUT_PROGRESS_DIR", "/tmp/scout-refresh")) / "progress.log"


DAY_MS = 86_400_000
HOUR_MS = 3_600_000
WINDOW_DAYS = 30

# ── stage A: universe (spec 7.2) ─────────────────────────────────────────
UNIVERSE_MIN_ACCOUNT_VALUE = _f("COPYCAT_SCOUT_MIN_AV", 10_000.0)
UNIVERSE_MIN_VLM_30D = _f("COPYCAT_SCOUT_MIN_VLM", 50_000.0)
UNIVERSE_SIZE = int(_f("COPYCAT_SCOUT_UNIVERSE", 300))
INCLUDE_VAULTS = os.environ.get("COPYCAT_SCOUT_INCLUDE_VAULTS", "0") == "1"

# ── schedule (spec 7.2) ──────────────────────────────────────────────────
STAGE_A_EVERY_S = _f("COPYCAT_SCOUT_A_EVERY_S", 15 * 60)
STAGE_B_EVERY_S = _f("COPYCAT_SCOUT_B_EVERY_S", 60 * 60)
SCHEDULER_TICK_S = 10.0
SCHEDULER_ALIVE_S = 90.0          # a scheduler heartbeat older than this = no scheduler
REFRESH_STALE_S = 15 * 60         # a `running` refresh with no heartbeat for this long is dead

# ── stage B budget: HL weight units per pass, and wall clock ─────────────
# HL gives 1200/min per IP; background callers keep 40% in reserve -> ~720/min.
# 40 minutes of that per hourly pass leaves the engine and manual runs room.
STAGE_B_MAX_WEIGHT = _f("COPYCAT_SCOUT_B_MAX_WEIGHT", 720 * 40)
STAGE_B_MAX_S = _f("COPYCAT_SCOUT_B_MAX_S", 50 * 60)
STAGE_C_MAX_WEIGHT = _f("COPYCAT_SCOUT_C_MAX_WEIGHT", 720 * 30)
STAGE_C_MAX_S = _f("COPYCAT_SCOUT_C_MAX_S", 40 * 60)
FAILS_BEFORE_SKIP = 2             # a wallet failing twice in a row sits out one cycle, flagged stale

# HL /info weights (services/hl/hl/rate_limit.py), used to charge the budget
W_PORTFOLIO = 20
W_ACCOUNT_STATE = 8               # clearinghouseState x dexes (2 each) + spot (2), typical 3 dexes
W_EXTRAS = 22                     # spotClearinghouseState 2 + delegatorSummary 20
W_FILLS_PAGE = 120                # hl charges 20 + 2000/20 up front per userFillsByTime page
W_CANDLES = 20                    # + bars/60, added per call
W_OPEN_ORDERS = 20

# ── metrics (spec section 2) ─────────────────────────────────────────────
MIN_AV_FOR_RETURN = 100.0         # #8: skip a day whose prior equity is below this
MIN_DAYS_FOR_RATIO = 7            # #10/#11: sharpe/sortino null below this many returns
STYLE_ALGO_OPENS_PER_DAY = 100.0  # #20
STYLE_SCALP_H = 0.25
STYLE_INTRADAY_H = 24.0
STYLE_SWING_H = 168.0
STYLE_MIN_TRIPS = 3
HL_FILLS_CAP = 10_000             # userFillsByTime reaches only the newest 10k fills
TRUNCATED_MIN_FILLS = 9_000       # at/above this many with the oldest after window start -> truncated
SPARK_MAX_POINTS = 60
RECENT_MAX = 100
CALENDAR_DAYS = 365
HIP3_PRESET_SHARE = 0.5

# ── serving ──────────────────────────────────────────────────────────────
DEFAULT_SIM_EQUITY_USD = _f("COPYCAT_SCOUT_SIM_EQUITY", 1_000.0)
KEEP_REFRESHES = 3
PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 50
ORDERS_TTL_S = 30.0
WHAT_IF_WAIT_S = 20.0
SIM_CURVE_STEP_MS = HOUR_MS       # used when sim.simulate_wallet exposes a curve hook
SIM_CURVE_FALLBACK_STEP_MS = DAY_MS
