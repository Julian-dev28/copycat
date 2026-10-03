"""Pure sizing and leverage math for the copy engine.

Every function here is deterministic and side-effect free: same inputs,
same output, every time, no I/O, no state, no venue calls. That is
deliberate -- `services/discovery`'s copy-sim imports these directly to
backtest "what would copying this leader at these settings have done"
without re-implementing the math and risking it drifting from what the
live engine actually does. Keep signatures stable; a breaking change here
breaks discovery's sim too.

Units follow contracts.models: USD for money, leverage as plain int,
percentages as percent (10.0 = 10%).
"""
from __future__ import annotations

import math

from contracts.models import HL_MIN_ORDER_USD, LeverageMode, Settings, SizingMode

# min_order_bump only rounds a notional UP to the exchange floor when it is
# already at least this fraction of the floor -- otherwise the gap is noise
# and a 10x bump off a near-zero notional would be absurd.
BUMP_FLOOR_FRAC = 0.25


def open_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                   our_equity: float, n_leaders: int, exchange_lev: int) -> float:
    """Dollar notional for a FRESH open under `settings.sizing_mode`.

    - proportional: `his_added_ntl / his_equity * allocation * size_multiplier`,
      where `allocation = our_equity * sleeve_frac / n_leaders` (a fixed,
      equal split across leaders, not weighted by his size). For a fresh
      open, `his_added_ntl` is the leader's FULL opening notional (his size
      times his own average entry price -- not the mark). Returns 0.0 if
      `his_equity <= 0` or `n_leaders <= 0`: never divide by zero, never
      size off a degraded or nonsensical read.
    - fixed_margin: `settings.fixed_margin_usd * exchange_lev`. A fixed
      dollar MARGIN at whatever leverage `exchange_leverage()` computed for
      this coin -- the mode a tiny account needs, since it never depends on
      the leader's or our own equity.
    - fixed_notional: `settings.fixed_notional_usd`, flat, independent of
      leverage entirely (leverage only changes margin USED, not position
      size).
    """
    if settings.sizing_mode == SizingMode.proportional:
        if his_equity <= 0 or n_leaders <= 0:
            return 0.0
        allocation = our_equity * settings.sleeve_frac / n_leaders
        return his_added_ntl / his_equity * allocation * settings.size_multiplier
    if settings.sizing_mode == SizingMode.fixed_margin:
        return settings.fixed_margin_usd * exchange_lev
    return settings.fixed_notional_usd


def add_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                  our_equity: float, n_leaders: int, our_current_notional: float,
                  his_frac_added: float) -> float:
    """Dollar notional for an ADD to an existing copy under `settings.sizing_mode`.

    - proportional: identical formula to `open_notional`'s proportional
      branch. `his_added_ntl` is now his INCREMENTAL notional (the size he
      just added times his entry), not his full position.
    - fixed_margin / fixed_notional: does NOT re-apply the fixed dollar
      amount -- that would re-fix the position back to the same size on
      every add and it would never grow with the leader. Instead scales OUR
      current notional by his fractional change:
      `our_current_notional * his_frac_added`, where `his_frac_added` is
      `(|his_cur| - |his_prev|) / |his_prev|`.

    Reduces, closes and flips never call this -- only an increase in the
    leader's absolute size does, in every sizing_mode.
    """
    if settings.sizing_mode == SizingMode.proportional:
        if his_equity <= 0 or n_leaders <= 0:
            return 0.0
        allocation = our_equity * settings.sleeve_frac / n_leaders
        return his_added_ntl / his_equity * allocation * settings.size_multiplier
    return our_current_notional * his_frac_added


def exchange_leverage(settings: Settings, his_lev: float, coin_max: int) -> int:
    """Exchange leverage to request for a coin under `settings.leverage_mode`,
    always capped by both the coin's own max leverage (`coin_max`) and
    `settings.max_position_leverage` -- in every mode, no exceptions:

    - max: the cap itself.
    - match: `ceil(his_lev)`, capped.
    - fixed: `settings.leverage`, capped.
    """
    cap = max(1, min(int(coin_max), int(settings.max_position_leverage)))
    if settings.leverage_mode == LeverageMode.match:
        return max(1, min(cap, math.ceil(his_lev)))
    if settings.leverage_mode == LeverageMode.fixed:
        return max(1, min(cap, int(settings.leverage)))
    return cap


def worse_entry_ok(side: str, mid: float, entry: float, pct: float) -> bool:
    """True when `mid` is within `pct` percent of the leader's own `entry`
    price (percent as in the contract: 10.0 = 10%) -- i.e. ok to open/add.

    A long is blocked once `mid > entry * (1 + pct/100)`; a short once
    `mid < entry * (1 - pct/100)`. `entry <= 0` (unknown/missing) always
    returns True: there is nothing to compare against, so this gate cannot
    apply. This only ever gates opens/adds -- reduces and closes never call
    it; exits always mirror regardless of price.
    """
    if entry <= 0:
        return True
    frac = pct / 100.0
    if side == "long":
        return mid <= entry * (1 + frac)
    return mid >= entry * (1 - frac)


def bump(notional: float, settings: Settings) -> float:
    """Round a sub-floor notional up to `HL_MIN_ORDER_USD` when
    `settings.min_order_bump` is on AND the notional is already at least
    `BUMP_FLOOR_FRAC` (25%) of the floor. Otherwise returns `notional`
    unchanged -- the caller is responsible for skipping it if it is still
    under the floor after this call. Already-adequate notionals pass
    through unchanged.
    """
    if notional >= HL_MIN_ORDER_USD:
        return notional
    if settings.min_order_bump and notional >= BUMP_FLOOR_FRAC * HL_MIN_ORDER_USD:
        return HL_MIN_ORDER_USD
    return notional


def liq_distance_pct(leverage: int, is_cross: bool, maint_frac: float) -> float:
    """Approximate adverse price-move percent, from entry, before liquidation:
    `(1/leverage - maint_frac) * 100`. At 40x isolated with a 1.25% maintenance
    fraction that is 1.25% -- this product has no stop anywhere, so this
    number IS the real distance to forced closure for an isolated position.

    `is_cross` changes what the number MEANS, not the formula: for an
    isolated position, this is the exact distance (ignoring funding/fees).
    For a CROSS position it is only a conservative single-position estimate
    -- cross liquidation draws on the whole account's free collateral, not
    just this position's own margin, so the true distance depends on every
    other cross position's PnL too and can be worse than this number if
    other cross positions are also underwater, or better if there is slack
    elsewhere on the account. Treat the cross case as "at least this close,
    possibly closer," never as exact.
    """
    return max(0.0, (1.0 / leverage - maint_frac) * 100.0)
