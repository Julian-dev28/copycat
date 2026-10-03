"""api-only request/response shapes. These never get imported by engine or
discovery; they're how the api accepts partial input and validates full
Settings before touching disk.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from contracts.models import (
    LeaderOverride,
    LeverageMode,
    MarginMode,
    Settings,
    SizingMode,
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


class HealthResponse(BaseModel):
    ok: bool
    version: str
