"""Shared contracts. Every service imports these; none reaches into another
service's internals. Changing a field here is a contract change: bump
CONTRACT_VERSION and update every side in the same commit.

Units: USD for money, plain floats for prices, leverage as int x,
percentages as percent (10.0 = 10%), timestamps as epoch milliseconds.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = 5   # v5: SmallAccountMode, liquidity caps, MAX_LEADERS 25, Venue.market_stats/depth_usd
# v4: v4: Trade page (allocation sizing, ExposureMode, wallet copy/stop, per-leader PnL)
# v3: Scout models (docs/research/copytrading_page_spec.md section 6)
# v2: Venue cloid/order_status/ambiguous, partial-fill semantics

MAX_LEADERS = 25                 # the engine stretches its poll interval to stay inside HL's read budget
HL_MIN_ORDER_USD = 10.5          # Hyperliquid rejects orders under $10; 10.5 leaves rounding room
MAX_LEVERAGE_CAP = 50            # >= every HL coin's max, so "max" mode == the coin's max

_ADDR = r"^0x[0-9a-f]{40}$"


def norm_addr(a: str) -> str:
    return str(a).strip().lower()


class SizingMode(str, Enum):
    fixed_margin = "fixed_margin"        # new copy posts this much margin at the exchange leverage
    fixed_notional = "fixed_notional"    # new copy is a flat notional
    proportional = "proportional"        # his exposure / his equity x our allocation x size_multiplier
    allocation = "allocation"            # "invest $X in this wallet" (Trade page): see ExposureMode


class LeverageMode(str, Enum):
    max = "max"          # the coin's max leverage
    match = "match"      # the leader's leverage on that coin
    fixed = "fixed"      # Settings.leverage


class ExposureMode(str, Enum):
    """How an `allocation` wallet turns the invested dollars into exposure.
    match:  his book at his own leverage. Copy notional = his notional / his equity x allocation_usd.
    target: his book at YOUR leverage. Copy notional = his notional / his gross notional
            x allocation_usd x target_leverage, i.e. allocation x L spread in his proportions."""
    match = "match"
    target = "target"


class SmallAccountMode(str, Enum):
    """What to do when a copy slice is under HL's $10.50 minimum (small allocations).
    concentrate: copy only the positions that clear the minimum and spread the whole
                 allocation across those, in the leader's proportions (his biggest bets).
    bump:        round a small slice up to the minimum while it fits the allocation cap.
    skip:        drop slices under the minimum."""
    concentrate = "concentrate"
    bump = "bump"
    skip = "skip"


class MarginMode(str, Enum):
    isolated = "isolated"
    cross = "cross"      # isolated-only markets are forced isolated by the hl service


class LeaderOverride(BaseModel):
    """Per-leader override. Absent field = inherit the book-wide value."""
    model_config = ConfigDict(extra="ignore")
    sizing_mode: Optional[SizingMode] = None
    size_multiplier: Optional[float] = Field(None, ge=0, le=100)
    fixed_margin_usd: Optional[float] = Field(None, ge=0.01)
    fixed_notional_usd: Optional[float] = Field(None, ge=HL_MIN_ORDER_USD)
    leverage_mode: Optional[LeverageMode] = None
    leverage: Optional[int] = Field(None, ge=1, le=MAX_LEVERAGE_CAP)
    margin_mode: Optional[MarginMode] = None
    max_worse_entry_pct: Optional[float] = Field(None, ge=0, le=100)
    # Trade page ("invest in a wallet"), used when sizing_mode is allocation
    allocation_usd: Optional[float] = Field(None, ge=0)
    exposure_mode: Optional[ExposureMode] = None
    target_leverage: Optional[int] = Field(None, ge=1, le=MAX_LEVERAGE_CAP)
    invested_ms: Optional[int] = None          # when this wallet was first invested in (set by the api)
    small_account_mode: Optional[SmallAccountMode] = None


class Settings(BaseModel):
    """The whole user-editable configuration. Stored at data/settings.json,
    owned by the api service (the only writer), read by the engine every cycle."""
    model_config = ConfigDict(extra="ignore")
    contract_version: int = CONTRACT_VERSION
    enabled: bool = False                       # real money: ships OFF
    dry_run: bool = True                        # engine reads for real, writes nothing, logs intent
    leaders: List[str] = Field(default_factory=list, max_length=MAX_LEADERS)
    sizing_mode: SizingMode = SizingMode.fixed_margin
    fixed_margin_usd: float = Field(1.0, ge=0.01)
    fixed_notional_usd: float = Field(HL_MIN_ORDER_USD, ge=HL_MIN_ORDER_USD)
    size_multiplier: float = Field(1.0, ge=0, le=100)
    sleeve_frac: float = Field(1.0, ge=0, le=1)  # proportional mode: share of our equity split across leaders
    leverage_mode: LeverageMode = LeverageMode.max
    leverage: int = Field(20, ge=1, le=MAX_LEVERAGE_CAP)
    max_position_leverage: int = Field(MAX_LEVERAGE_CAP, ge=1, le=MAX_LEVERAGE_CAP)
    margin_mode: MarginMode = MarginMode.isolated
    include_spot_staked: bool = False
    only_new_positions: bool = False
    max_worse_entry_pct: float = Field(10.0, ge=0, le=100)
    min_order_bump: bool = True                 # bump to HL_MIN_ORDER_USD when >= 25% of it
    daily_loss_limit_usd: float = Field(0.0, le=0)   # 0 = off; else no new opens/adds once day PnL <= this
    max_open_copies: int = Field(10, ge=1, le=50)
    poll_interval_s: float = Field(5.0, ge=2, le=300)
    leader_overrides: Dict[str, LeaderOverride] = Field(default_factory=dict)
    # Book-wide defaults for allocation wallets; the Trade ticket sets them per wallet.
    allocation_usd: float = Field(0.0, ge=0)
    exposure_mode: ExposureMode = ExposureMode.match
    target_leverage: int = Field(5, ge=1, le=MAX_LEVERAGE_CAP)
    invested_ms: Optional[int] = None
    small_account_mode: SmallAccountMode = SmallAccountMode.concentrate
    # Large accounts: one order is capped at this % of the coin's 24h volume and at the book
    # depth within the slippage cap; the rest fills over the next cycles.
    max_order_volume_pct: float = Field(0.5, gt=0, le=100)
    max_slippage_pct: float = Field(1.0, gt=0, le=10)

    @field_validator("leaders")
    @classmethod
    def _leaders(cls, v: List[str]) -> List[str]:
        import re
        out: List[str] = []
        for a in v:
            a = norm_addr(a)
            if not re.match(_ADDR, a):
                raise ValueError(f"not a 0x address: {a!r}")
            if a not in out:
                out.append(a)
        return out[:MAX_LEADERS]

    @field_validator("leader_overrides")
    @classmethod
    def _overrides(cls, v: Dict[str, LeaderOverride]) -> Dict[str, LeaderOverride]:
        return {norm_addr(k): o for k, o in v.items()}

    def for_leader(self, leader: str) -> "Settings":
        """Effective settings for one leader: book-wide merged with its override."""
        o = self.leader_overrides.get(norm_addr(leader))
        if not o:
            return self
        patch = {k: val for k, val in o.model_dump().items() if val is not None}
        return self.model_copy(update=patch)


# ── engine → api (read models) ───────────────────────────────────────────────

class CopyPosition(BaseModel):
    coin: str                       # "BTC" or "xyz:TSLA"
    leader: str
    side: Literal["long", "short"]
    size: float                     # signed szi on our account
    entry_px: float
    mark_px: float
    notional_usd: float
    leverage: int
    is_cross: bool
    unrealized_pnl_usd: float
    liquidation_px: Optional[float] = None
    opened_ms: int
    sizing_mode: SizingMode


class EngineEvent(BaseModel):
    """One line of the engine's append-only event log (data/events.jsonl)."""
    ts_ms: int
    action: Literal["baseline", "open", "add", "reduce", "close", "skip", "error",
                    "intent", "halt", "resume"]
    leader: Optional[str] = None
    coin: Optional[str] = None
    side: Optional[Literal["long", "short"]] = None
    notional_usd: Optional[float] = None
    leverage: Optional[int] = None
    reason: Optional[str] = None    # skip/error reason, human readable
    dry_run: bool = False


class LeaderStatus(BaseModel):
    address: str
    read_ok: bool
    equity_usd: Optional[float] = None
    open_positions: int = 0
    owned_coins: List[str] = Field(default_factory=list)   # coins we mirror from this leader
    last_read_ms: Optional[int] = None
    effective: Settings
    # per-wallet "position" for the Trade page (our copies of this leader only)
    open_copies: int = 0
    margin_used_usd: float = 0.0
    exposure_usd: float = 0.0                  # sum |notional| of our copies
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0              # since invested_ms, from our own closes/reduces
    fees_usd: float = 0.0
    stopping: bool = False                     # a stop-and-close is in progress


class EngineStatus(BaseModel):
    running: bool
    enabled: bool
    dry_run: bool
    last_cycle_ms: Optional[int] = None
    cycle_ms: Optional[int] = None          # duration of the last cycle
    our_address: Optional[str] = None
    equity_usd: Optional[float] = None
    available_margin_usd: Optional[float] = None
    day_pnl_usd: Optional[float] = None
    halted_reason: Optional[str] = None     # daily loss limit etc.
    positions: List[CopyPosition] = Field(default_factory=list)
    leaders: List[LeaderStatus] = Field(default_factory=list)


# ── discovery → api ──────────────────────────────────────────────────────────

class TraderScore(BaseModel):
    """One ranked candidate. Ranked by what COPYING him would have earned at
    the given settings, not by his own PnL."""
    address: str
    display_name: Optional[str] = None
    account_value_usd: float
    pnl_30d_usd: float
    roi_30d_pct: float
    pnl_all_time_usd: float
    volume_30d_usd: float
    fills_30d: int
    opens_per_day: float
    median_hold_h: Optional[float] = None
    coins: List[str] = Field(default_factory=list)
    # copy-sim at the run's settings
    sim_return_pct: float               # on the simulated copier's starting equity
    sim_max_drawdown_pct: float         # <= 0
    sim_liquidations: int
    sim_copies: int                     # copies the sim actually opened
    sim_skipped_min_order: int
    sim_fees_usd: float
    score: float                        # the ranking key, higher is better
    flags: List[str] = Field(default_factory=list)   # e.g. "hft", "vault", "too_few_trades"
    # v3 (Scout): optional so v2 rows still validate
    sim_copy_capacity_pct: Optional[float] = None
    copy_fit: Optional["CopyFit"] = None
    style: Optional["TradingStyle"] = None
    last_fill_ms: Optional[int] = None


class DiscoveryRun(BaseModel):
    run_id: str
    started_ms: int
    finished_ms: Optional[int] = None
    status: Literal["running", "done", "failed"]
    sim_equity_usd: float
    sim_settings: Settings
    candidates: int                     # wallets pulled from the leaderboard
    scored: int
    error: Optional[str] = None
    results: List[TraderScore] = Field(default_factory=list)


# ── Scout (v3): trader board + trader file. docs/research/copytrading_page_spec.md ──

class PnlWindow(str, Enum):
    day = "1d"
    week = "7d"
    month = "30d"
    all_time = "all"

class TradingStyle(str, Enum):
    algo = "algo"
    scalp = "scalp"
    intraday = "intraday"
    swing = "swing"
    position = "position"

class SizeTier(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"
class PnlTier(str, Enum):
    losing = "losing"
    up = "up"
    strong = "strong"
    elite = "elite"

class CurvePoint(BaseModel):
    t_ms: int
    value: float                         # USD

class WindowPerf(BaseModel):             # straight from the stats-data leaderboard
    window: PnlWindow
    pnl_usd: float
    roi_pct: float
    volume_usd: float

class RiskStats(BaseModel):              # from portfolio pnl/accountValue history
    window: PnlWindow
    max_drawdown_pct: Optional[float] = None    # >= 0
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    profitable_days_pct: Optional[float] = None
    days: int = 0

class TradeStats(BaseModel):             # from reconstructed round trips
    window: PnlWindow
    trips: int
    wins: int
    long_trips: int
    short_trips: int
    win_rate_pct: Optional[float] = None
    avg_hold_h: Optional[float] = None
    median_hold_h: Optional[float] = None
    opens_per_day: float = 0.0

class CoinStat(BaseModel):
    coin: str
    volume_usd: float
    pnl_usd: float
    trips: int = 0

class CopyFit(BaseModel):
    value: float                         # 0..100
    parts: Dict[str, float]              # part name -> 0..1 (pre-weight)
    weights: Dict[str, float]
    caps: List[str] = Field(default_factory=list)   # flags that capped it
    cohort_size: int



class TraderRow(BaseModel):              # one Scout board row; what the list route returns
    address: str
    display_name: Optional[str] = None
    account_value_usd: float
    size_tier: SizeTier
    pnl_tier: PnlTier
    style: Optional[TradingStyle] = None
    last_fill_ms: Optional[int] = None
    perf: List[WindowPerf]               # 1d, 7d, 30d, all
    risk_30d: RiskStats
    trades_30d: TradeStats
    top_coins: List[CoinStat] = Field(default_factory=list, max_length=5)
    pnl_spark_30d: List[CurvePoint] = Field(default_factory=list, max_length=60)
    sim_spark_30d: List[CurvePoint] = Field(default_factory=list, max_length=60)
    score: TraderScore                   # sim + Copy Fit at settings_hash
    in_book: bool = False                # filled by api from Settings.leaders
    flags: List[str] = Field(default_factory=list)

class TraderPage(BaseModel):
    as_of_ms: int
    refresh_id: str
    settings_hash: str
    cohort_size: int
    total: int                           # after filters
    rows: List[TraderRow]
    stale_settings: bool = False         # rows were scored at an older settings_hash (spec 7.3)

class TraderPositionView(BaseModel):
    coin: str
    side: Literal["long", "short"]
    size: float
    notional_usd: float
    entry_px: float
    mark_px: float
    unrealized_pnl_usd: float
    roe_pct: float
    leverage: int
    is_cross: bool
    liquidation_px: Optional[float] = None
    liq_distance_pct: Optional[float] = None
    margin_usd: float
    funding_since_open_usd: float

class RoundTrip(BaseModel):
    coin: str
    side: Literal["long", "short"]
    opened_ms: int
    closed_ms: int
    hold_h: float
    entry_px: float                      # size-weighted avg of opens/adds
    exit_px: float                       # size-weighted avg of reduces/close
    max_notional_usd: float
    net_pnl_usd: float                   # closed_pnl - fees
    win: bool

class AccountRisk(BaseModel):
    perps_usd: float
    spot_usd: float
    staked_usd: float
    account_leverage: float
    margin_usage_pct: float
    nearest_liq_pct: Optional[float] = None
    long_notional_usd: float
    short_notional_usd: float
    long_bias_pct: Optional[float] = None
    unrealized_pnl_usd: float

class LeaderFillView(BaseModel):         # display shape of a leader fill
    time_ms: int
    coin: str
    side: Literal["B", "A"]
    dir: str
    px: float
    sz: float
    notional_usd: float
    closed_pnl_usd: float
    fee_usd: float


class TraderProfile(BaseModel):          # the Trader file
    row: TraderRow
    account: AccountRisk
    positions: List[TraderPositionView]
    positions_as_of_ms: int
    pnl_curve: Dict[PnlWindow, List[CurvePoint]]
    value_curve: Dict[PnlWindow, List[CurvePoint]]
    sim_curve: List[CurvePoint]          # hourly, 30d, at settings_hash
    daily_pnl: List[CurvePoint]          # calendar, last 365 days, t = UTC midnight
    risk: List[RiskStats]                # 7d, 30d, all
    trades: List[TradeStats]             # 7d, 30d
    longest_win_streak_days: int
    coins: List[CoinStat]
    recent_trips: List[RoundTrip] = Field(default_factory=list, max_length=100)
    recent_fills: List[LeaderFillView] = Field(default_factory=list, max_length=100)



class WhatIfRequest(BaseModel):
    sim_equity_usd: float = Field(gt=0)
    override: LeaderOverride             # reuses the existing per-leader override shape

class WhatIfResult(BaseModel):
    score: TraderScore                   # sim fields only; copy_fit None (no cohort)
    sim_curve: List[CurvePoint]

class ScoutStatus(BaseModel):
    refresh_id: Optional[str]
    state: Literal["idle", "running", "failed"]
    stage: Optional[Literal["leaderboard", "stats", "sim"]] = None
    done: int = 0
    total: int = 0
    eta_s: Optional[float] = None
    last_ok_ms: Optional[int] = None
    next_due_ms: Optional[int] = None
    error: Optional[str] = None


class OpenOrderView(BaseModel):          # v3.1: display shape of a trader's resting order (GET .../orders)
    oid: int
    coin: str
    side: Literal["B", "A"]               # B = bid (buy), A = ask (sell), as in LeaderFillView
    order_type: str = "Limit"            # HL orderType, e.g. "Limit", "Stop Market", "Take Profit Limit"
    limit_px: float
    sz: float                            # remaining
    orig_sz: float
    notional_usd: float                  # limit_px * sz
    reduce_only: bool = False
    is_trigger: bool = False
    trigger_px: Optional[float] = None
    trigger_condition: Optional[str] = None
    tif: Optional[str] = None            # "Gtc", "Alo", "Ioc"; None for triggers
    time_ms: int                         # placed at

class ScoutPresets(BaseModel):           # v3.1: preset tabs + coin chips (GET /api/scout/presets)
    refresh_id: Optional[str] = None     # the scout_rows refresh these counts come from
    coins: List[str] = Field(default_factory=list)            # chip order, most traders first
    coin_counts: Dict[str, int] = Field(default_factory=dict)  # coin -> traders with it in top coins
    hip3_count: int = 0                  # traders with any HIP-3 coin in top coins
    total: int = 0                       # rows in the "all" tab


TraderScore.model_rebuild()
DiscoveryRun.model_rebuild()


# ── Strategy thesis (v3.1): what a trader actually does, so users can learn ──
# Two sources, same shape:
#   "ta"          deterministic fingerprint from fills + candles (services/discovery thesis module)
#   "claude_code" written by the user's Claude Code through the copycat MCP server (services/mcp)

class EntryContext(BaseModel):
    """Market state at one entry, from candles. All deterministic."""
    trend_aligned: Optional[bool] = None       # side matches the 1h EMA50 slope
    breakout: Optional[bool] = None            # long within 0.5% of the 20-bar high / short of the low
    pullback: Optional[bool] = None            # long >= 2% under the 20-bar high and above EMA50 (mirror for shorts)
    rsi_14: Optional[float] = None             # 1h RSI at entry
    move_24h_pct: Optional[float] = None       # coin's move over the 24h before entry
    hour_utc: int


class TradeExample(BaseModel):
    """One representative round trip shown as evidence for a fingerprint claim."""
    coin: str
    side: Literal["long", "short"]
    opened_ms: int
    closed_ms: int
    hold_h: float
    adds: int
    max_leverage: Optional[float] = None
    net_pnl_usd: float
    return_pct: float                          # on max notional
    context: EntryContext
    why_shown: str                             # e.g. "largest win", "typical breakout entry"


class StrategyFingerprint(BaseModel):
    address: str
    as_of_ms: int
    window_days: int
    trips_analyzed: int
    style: Optional[TradingStyle] = None
    median_hold_h: Optional[float] = None
    p90_hold_h: Optional[float] = None
    long_pct: Optional[float] = None           # share of trips that are long, 0..100
    # entry habits (share of trips, 0..100; None when candles were unavailable)
    trend_aligned_pct: Optional[float] = None
    breakout_pct: Optional[float] = None
    pullback_pct: Optional[float] = None
    avg_rsi_long_entry: Optional[float] = None
    avg_rsi_short_entry: Optional[float] = None
    # sizing
    avg_adds_per_trip: Optional[float] = None
    scales_in_pct: Optional[float] = None      # trips with >= 1 add
    scales_out_pct: Optional[float] = None     # trips closed in >= 2 reduces
    avg_leverage: Optional[float] = None
    max_leverage: Optional[float] = None
    # outcomes
    win_rate_pct: Optional[float] = None
    avg_win_usd: Optional[float] = None
    avg_loss_usd: Optional[float] = None       # negative
    payoff_ratio: Optional[float] = None       # avg win / |avg loss|
    loser_hold_vs_winner: Optional[float] = None   # median loser hold / median winner hold (< 1 = cuts losers fast)
    worst_trip_pct_of_equity: Optional[float] = None
    pnl_from_top_coin_pct: Optional[float] = None  # concentration
    # timing
    hour_hist_utc: List[int] = Field(default_factory=list)      # 24 buckets, trip entries
    weekday_hist: List[int] = Field(default_factory=list)       # 7 buckets, Monday first
    top_coins: List[CoinStat] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)  # e.g. "trend follower", "dip buyer", "scales in"
    summary: str                               # templated plain-English thesis, no AI
    examples: List[TradeExample] = Field(default_factory=list, max_length=8)
    caveats: List[str] = Field(default_factory=list)   # e.g. "only 12 trips", "candles missing for xyz coins"


class Thesis(BaseModel):
    """A written strategy thesis for one trader. `ta` ones are regenerated
    from the fingerprint; `claude_code` ones are saved through the MCP
    server and kept until replaced."""
    address: str
    source: Literal["ta", "claude_code"]
    created_ms: int
    title: str
    markdown: str = Field(max_length=20_000)
    fingerprint_as_of_ms: Optional[int] = None
    author: Optional[str] = None               # e.g. "claude-opus-5-5 via copycat MCP"



# ── Trade page (v3.2): invest in a wallet like a perp ───────────────────────

class WalletCopyRequest(BaseModel):
    """POST /api/wallets/{address}/copy: add the wallet to the book (if new)
    and set its allocation in one atomic settings write."""
    model_config = ConfigDict(extra="forbid")
    allocation_usd: float = Field(gt=0)
    exposure_mode: ExposureMode = ExposureMode.match
    target_leverage: Optional[int] = Field(None, ge=1, le=MAX_LEVERAGE_CAP)   # required for target
    margin_mode: Optional[MarginMode] = None
    max_worse_entry_pct: Optional[float] = Field(None, ge=0, le=100)
    small_account_mode: Optional[SmallAccountMode] = None


class WalletStopRequest(BaseModel):
    """POST /api/wallets/{address}/stop. close_positions true: close our copies
    of this wallet now (reduce-only, like close-all for one wallet). False: stop
    opening new copies and let the open ones follow him out."""
    model_config = ConfigDict(extra="forbid")
    close_positions: bool = True
