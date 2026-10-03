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


# Hyperliquid account abstraction modes in which ONE spot balance per asset
# collateralizes every perp dex (HL docs, "Account abstraction modes":
# "unified account and portfolio margin show all balances and holds in the
# spot clearinghouse state. Individual perp dex user states are not
# meaningful."). `userAbstraction` returns one of
# "unifiedAccount" | "portfolioMargin" | "disabled" | "default" | "dexAbstraction".
UNIFIED_ABSTRACTIONS = frozenset({"unifiedAccount", "portfolioMargin"})


def account_equity(account: dict) -> float:
    """Equity in USD for one `contracts.venue.AccountState`.

    - Standard / dex-abstraction / unknown mode: perp `accountValue` summed
      over the dexes read, plus spot USDC. Spot and perp are separate
      balances in these modes, so the sum is the account.
    - Unified account / portfolio margin (`account["abstraction"]` in
      `UNIFIED_ABSTRACTIONS`): spot USDC `total` already holds the perp
      collateral (HL reserves it as spot `hold`), so adding perp
      `accountValue` on top double counts it. Measured on mainnet
      2026-10-03 on a USDC-only unified wallet: perp+spot = $966k against
      HL's own portfolio value of $534k. Spot `total` does NOT include
      open-position PnL, so it is added back from each position's
      `unrealizedPnl`: spot USDC + uPnL = $527k, within 1.5% of HL's value.

    The mode comes from an optional `abstraction` key on the account read.
    When it is missing (the hl service does not populate it yet) this
    falls back to the standard formula, which is the pre-existing behavior.
    """
    perp = float(account.get("equity_perp_usd") or 0.0)
    spot = float(account.get("spot_usdc") or 0.0)
    if account.get("abstraction") in UNIFIED_ABSTRACTIONS:
        upnl = 0.0
        for raw in (account.get("raw_positions") or {}).values():
            try:
                upnl += float((raw or {}).get("unrealizedPnl") or 0.0)
            except (TypeError, ValueError):
                continue
        return spot + upnl
    return perp + spot
