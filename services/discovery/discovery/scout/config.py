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
# A running refresh beats both heartbeats from its own thread this often (refresh.Heartbeat),
# so liveness is a property of the process, not of per-wallet progress: one slow wallet
# (stage B p95 215 s live; a stage C wallet starved of candles sat 15 min) used to flip
# health to `alive: False` after SCHEDULER_ALIVE_S and the status to "failed (process died)"
# after REFRESH_STALE_S while the scout was alive and working.
REFRESH_HEARTBEAT_S = 20.0

# ── stage B budget: HL weight units per pass, and wall clock ─────────────
# HL gives 1200/min per IP; background callers keep 40% in reserve -> ~720/min.
# 40 minutes of that per hourly pass leaves the engine and manual runs room.
STAGE_B_MAX_WEIGHT = _f("COPYCAT_SCOUT_B_MAX_WEIGHT", 720 * 40)
STAGE_B_MAX_S = _f("COPYCAT_SCOUT_B_MAX_S", 50 * 60)
STAGE_C_MAX_WEIGHT = _f("COPYCAT_SCOUT_C_MAX_WEIGHT", 720 * 30)
STAGE_C_MAX_S = _f("COPYCAT_SCOUT_C_MAX_S", 40 * 60)
FAILS_BEFORE_SKIP = 2             # a wallet failing twice in a row sits out one cycle, flagged stale

# ── stage B warm path (indexing tightening, 2026-10) ──────────────────────
# account_state, extras, userFunding and the one-time liquidation backfill move off the
# hourly cadence onto this slower one. A wallet still gets them right away when a new
# fill just landed (its account genuinely changed) or on its first-ever build.
FULL_REFRESH_EVERY_S = _f("COPYCAT_SCOUT_FULL_EVERY_S", 6 * 60 * 60)
# Per-wallet cap on real userFillsByTime pages ANY one sync_fills call may spend (first-ever
# sync, or a wallet whose tail has not caught up yet): a 53,520-fill wallet backfilling 30d
# in one call paid 27 pages (3,240 weight) in a single pass; this bounds that to
# MAX_FILLS_PAGES_PER_WALLET, honestly short on the recent edge (flagged fills_truncated),
# caught up over the next few passes as the tail keeps advancing forward.
MAX_FILLS_PAGES_PER_WALLET = int(_f("COPYCAT_SCOUT_MAX_FILLS_PAGES", 5))
# ETA honesty gate (refresh.eta_s): no estimate until BOTH are met (10 wallets AND 10% of the pass).
ETA_MIN_DONE = int(_f("COPYCAT_SCOUT_ETA_MIN_DONE", 10))
ETA_MIN_FRAC = _f("COPYCAT_SCOUT_ETA_MIN_FRAC", 0.10)

# HL /info weights (services/hl/hl/rate_limit.py), used to charge the budget.
# tests/invariants/test_hl_weights.py pins every derived one to hl's own rule.
W_INFO = 20                       # base weight of every documented /info request
ITEMS_PER_WEIGHT = 20             # +1 per 20 rows a paginated read returns (userFillsByTime, userFunding)
W_PORTFOLIO = 20
W_ACCOUNT_STATE = 8               # clearinghouseState x dexes (2 each) + spot (2), typical 3 dexes
W_EXTRAS = 22                     # spotClearinghouseState 2 + delegatorSummary 20
FILLS_PAGE_ROWS = 2000            # hl.venue.fills' real page size
FUNDING_PAGE_ROWS = 500           # hl.venue.funding's real page size
# A FULL page's cost: the worst case `stats.estimate_weight` admits a wallet against. The budget is
# CHARGED what HL metered for the pages that actually came back (HlVenue.last_read, or the rule above
# on the rows returned): a 12-row warm tail costs 21, not 120.
W_FILLS_PAGE = W_INFO + FILLS_PAGE_ROWS // ITEMS_PER_WEIGHT       # 120
W_FUNDING_PAGE = W_INFO + FUNDING_PAGE_ROWS // ITEMS_PER_WEIGHT   # 45
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
