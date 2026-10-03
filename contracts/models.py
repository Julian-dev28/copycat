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

CONTRACT_VERSION = 2   # v2: Venue cloid/order_status/ambiguous, partial-fill semantics

MAX_LEADERS = 10
HL_MIN_ORDER_USD = 10.5          # Hyperliquid rejects orders under $10; 10.5 leaves rounding room
MAX_LEVERAGE_CAP = 50            # >= every HL coin's max, so "max" mode == the coin's max

_ADDR = r"^0x[0-9a-f]{40}$"


def norm_addr(a: str) -> str:
    return str(a).strip().lower()


class SizingMode(str, Enum):
    fixed_margin = "fixed_margin"        # new copy posts this much margin at the exchange leverage
    fixed_notional = "fixed_notional"    # new copy is a flat notional
    proportional = "proportional"        # his exposure / his equity x our allocation x size_multiplier


class LeverageMode(str, Enum):
    max = "max"          # the coin's max leverage
    match = "match"      # the leader's leverage on that coin
    fixed = "fixed"      # Settings.leverage


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
