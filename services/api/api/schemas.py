"""api-only request/response shapes. These never get imported by engine or
discovery; they're how the api accepts partial input and validates full
Settings before touching disk.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.models import (
    ExposureMode,
    LeaderOverride,
    LeverageMode,
    MarginMode,
    PnlWindow,
    Settings,
    SizingMode,
    SmallAccountMode,
    TradeDirection,
    TradingStyle,
)


class SettingsPatch(BaseModel):
    """Partial Settings for PATCH /api/settings.

    Every field is Optional and "unset" (not just None) means "leave as
    is" -- SettingsStore.patch() checks `model_fields_set`, not `is None`,
    for every field except leader_overrides, where None is the documented
    "clear this leader's override" sentinel.

    Range constraints (ge/le, max_length) are intentionally NOT duplicated
    here. contracts.models.Settings is the single source of truth for
    valid ranges; SettingsStore.patch() re-validates the merged result
    through it before writing, which still 422s a bad value, just one
    layer later, with the file-untouched guarantee coming from
    validate-then-write ordering in SettingsStore.patch().
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Optional[int] = None
    enabled: Optional[bool] = None
    dry_run: Optional[bool] = None
    leaders: Optional[List[str]] = None
    sizing_mode: Optional[SizingMode] = None
    fixed_margin_usd: Optional[float] = None
    fixed_notional_usd: Optional[float] = None
    size_multiplier: Optional[float] = None
    sleeve_frac: Optional[float] = None
    leverage_mode: Optional[LeverageMode] = None
    leverage: Optional[int] = None
    max_position_leverage: Optional[int] = None
    margin_mode: Optional[MarginMode] = None
    include_spot_staked: Optional[bool] = None
    only_new_positions: Optional[bool] = None
    max_worse_entry_pct: Optional[float] = None
    min_order_bump: Optional[bool] = None
    daily_loss_limit_usd: Optional[float] = None
    max_open_copies: Optional[int] = None
    poll_interval_s: Optional[float] = None
    allocation_usd: Optional[float] = None
    exposure_mode: Optional[ExposureMode] = None
    target_leverage: Optional[int] = None
    invested_ms: Optional[int] = None
    small_account_mode: Optional[SmallAccountMode] = None
    max_order_volume_pct: Optional[float] = None
    max_slippage_pct: Optional[float] = None
    # v8 book-wide defaults (a wallet override replaces them)
    trade_direction: Optional[TradeDirection] = None
    coin_allowlist: Optional[List[str]] = None
    coin_blocklist: Optional[List[str]] = None
    paused: Optional[bool] = None
    # address -> override. None clears that leader's override; a value
    # REPLACES whatever override that leader had, wholesale (not merged
    # field by field with the old override).
    leader_overrides: Optional[Dict[str, Optional[LeaderOverride]]] = None


class AddLeaderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str


class DiscoveryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sim_equity_usd: float
    top_n: int
    settings: Optional[Settings] = None


class DiscoveryRunResponse(BaseModel):
    run_id: str


class ComponentBuild(BaseModel):
    """One process's code identity (contracts.build). `build` None: unknown
    (the process never recorded one: not started, or started on older code)."""
    component: str
    build: Optional[str] = None
    contract_version: Optional[int] = None
    started_ms: Optional[int] = None
    alive: bool = False


class HealthResponse(BaseModel):
    ok: bool
    version: str
    # the running contracts.models.CONTRACT_VERSION (audit H4): the web's feature caps
    # read this, never a value stored in settings.json
    contract_version: int
    # audit M12: every long-running process's build, and the ones running other
    # code than this api (restart them). Empty `stale` = all on the same code.
    builds: List[ComponentBuild] = Field(default_factory=list)
    stale: List[str] = Field(default_factory=list)
    # the code on disk (git HEAD, plus a hash when edited). When it differs from the
    # api's own build, "api" is in `stale` too: restart it after a pull.
    checkout_build: Optional[str] = None


class CloseAllResponse(BaseModel):
    """POST /api/engine/close-all. `settings` has `enabled` false already;
    the closes themselves happen on the engine's next cycle (watch
    /api/events for `close` events with reason "close-all", then a `halt`
    event "close-all complete ...")."""
    requested_ms: int
    pending: bool
    settings: Settings


class WalletStopResponse(BaseModel):
    """POST /api/wallets/{address}/stop. `settings` no longer has the wallet.
    `stopping` true: a stop-and-close is pending; the engine closes the copies
    on its next cycles (events: `close` reason "stop wallet", then `skip`
    "wallet stopped") and `GET /api/wallets` shows the row winding down."""
    settings: Settings
    stopping: bool


# ── Scout (docs/research/copytrading_page_spec.md sections 5 and 8) ─────────

SCOUT_MAX_LIMIT = 200
SCOUT_FILLS_MAX_LIMIT = 500


class ScoutSort(str, Enum):
    fit = "fit"
    sim_return = "sim_return"
    sim_dd = "sim_dd"
    pnl = "pnl"
    roi = "roi"
    account_value = "account_value"
    sharpe = "sharpe"
    max_dd = "max_dd"
    win_rate = "win_rate"
    trips = "trips"
    last_active = "last_active"
    volume = "volume"


class ScoutQuery(BaseModel):
    """Query params of GET /api/scout/traders (spec section 5). Validated
    here, then handed to `discovery.scout.public.scout_page` as a plain dict
    (`to_discovery()`), so discovery never imports the api. Unknown params
    are a 422, not silently ignored: a typo'd filter must not look like
    "no filter"."""
    model_config = ConfigDict(extra="forbid")

    window: PnlWindow = PnlWindow.month
    preset: str = Field("all", pattern=r"^(all|hip3|custom|coin:[A-Za-z0-9_:.\-]{1,32})$")
    coin: List[str] = Field(default_factory=list, max_length=20)
    min_av: Optional[float] = Field(None, ge=0)
    max_av: Optional[float] = Field(None, ge=0)
    min_pnl: Optional[float] = None
    max_pnl: Optional[float] = None
    style: List[TradingStyle] = Field(default_factory=list)
    min_fit: Optional[float] = Field(None, ge=0, le=100)
    max_fit: Optional[float] = Field(None, ge=0, le=100)
    max_dd: Optional[float] = Field(None, ge=0, le=100)
    min_trips: Optional[int] = Field(None, ge=0)
    active_within_h: Optional[int] = Field(None, ge=1, le=24 * 366)
    hide_flagged: bool = False
    q: Optional[str] = Field(None, min_length=1, max_length=64)
    sort: ScoutSort = ScoutSort.fit
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(50, ge=1, le=SCOUT_MAX_LIMIT)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _ranges(self) -> "ScoutQuery":
        for lo, hi in (("min_av", "max_av"), ("min_pnl", "max_pnl"), ("min_fit", "max_fit")):
            a, b = getattr(self, lo), getattr(self, hi)
            if a is not None and b is not None and a > b:
                raise ValueError(f"{lo} ({a}) > {hi} ({b})")
        for c in self.coin:
            if not c or len(c) > 32:
                raise ValueError(f"bad coin {c!r}")
        return self

    def to_discovery(self) -> Dict[str, Any]:
        """Every key from spec section 5, enums as their string values,
        repeatable params as lists (deduped, order kept)."""
        d = self.model_dump(mode="json")
        d["coin"] = list(dict.fromkeys(self.coin))
        d["style"] = list(dict.fromkeys(s.value for s in self.style))
        if self.q is not None:
            d["q"] = self.q.strip()
        return d


# ── Strategy thesis + market data ────────────────────────────────────────────

THESIS_MARKDOWN_MAX = 20_000
TRADES_MAX_LIMIT = 8        # StrategyFingerprint.examples max_length


class ThesisWrite(BaseModel):
    """PUT /api/scout/traders/{address}/thesis. The server sets `source`
    ("claude_code", always), `address` and `created_ms`; a body carrying
    any of them is a 422 (extra="forbid"), so a client can never write a
    "ta" thesis."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=THESIS_MARKDOWN_MAX)
    author: Optional[str] = Field(None, max_length=200)


# HL candleSnapshot intervals, in ms (same table as discovery.candles_cache).
CANDLE_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}
CANDLE_MAX_BARS = 5000      # HL serves at most ~5000 bars per interval


class CandleQuery(BaseModel):
    """GET /api/market/candles. Range is [start_ms, end_ms], capped at
    CANDLE_MAX_BARS bars of `interval`."""
    model_config = ConfigDict(extra="forbid")
    coin: str = Field(pattern=r"^[A-Za-z0-9_:.\-]{1,32}$")
    interval: Literal["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _range(self) -> "CandleQuery":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be > start_ms")
        bars = (self.end_ms - self.start_ms) // CANDLE_INTERVAL_MS[self.interval] + 1
        if bars > CANDLE_MAX_BARS:
            raise ValueError(f"range is {bars} {self.interval} bars; max {CANDLE_MAX_BARS}")
        return self


class CandleView(BaseModel):
    t_ms: int               # bar open time
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
