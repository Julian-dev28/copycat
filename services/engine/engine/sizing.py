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
from typing import Any, Dict, Iterable, List, Mapping, Optional

from contracts.models import (
    HL_MIN_ORDER_USD,
    ExposureMode,
    LeverageMode,
    Settings,
    SizingMode,
    SmallAccountMode,
)

# min_order_bump only rounds a notional UP to the exchange floor when it is
# already at least this fraction of the floor -- otherwise the gap is noise
# and a 10x bump off a near-zero notional would be absurd.
BUMP_FLOOR_FRAC = 0.25


# Allocation cap slack: a wallet's total copy margin may run this much over
# `allocation_usd` (rounding to szDecimals and the $10.50 bump need a little room).
ALLOCATION_SLACK = 1.02


def allocation_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                        his_gross_ntl_after: float, lev: Optional[int] = None) -> float:
    """`allocation` sizing ("invest $X in this wallet", the Trade page), for
    an open or an add alike (`his_added_ntl` is his full opening notional or
    his incremental add, both at his entry price):

    - exposure_mode match:  `his_added_ntl / his_equity * allocation_usd`.
      His book at his own leverage: if he runs 3x, $1,000 invested carries
      about $3,000 of notional.
    - exposure_mode target: `his_added_ntl / his_gross_ntl_after *
      allocation_usd * lev`, where `his_gross_ntl_after` is the sum of
      |notional| over his whole book AFTER this change and `lev` is the
      exchange leverage this copy runs at (`exchange_leverage`: the
      target_leverage, capped by the coin max and max_position_leverage;
      None = target_leverage). Using the CAPPED leverage keeps every
      slice's margin at exactly `allocation_usd * his weight`, so the whole
      wallet's margin is the allocation even on a coin that cannot reach L.

    Returns 0.0 on a zero/negative denominator (never divide by zero, never
    size off a degraded read) or a non-positive allocation."""
    alloc = float(settings.allocation_usd or 0.0)
    if alloc <= 0 or his_added_ntl <= 0:
        return 0.0
    if settings.exposure_mode == ExposureMode.target:
        if his_gross_ntl_after <= 0:
            return 0.0
        lev_used = int(lev) if lev else int(settings.target_leverage)
        return his_added_ntl / his_gross_ntl_after * alloc * lev_used
    if his_equity <= 0:
        return 0.0
    return his_added_ntl / his_equity * alloc


def allocation_room_ntl(settings: Settings, margin_used_usd: float, exchange_lev: int) -> float:
    """Most notional a new open/add for an `allocation` wallet may carry so
    that this wallet's total copy margin (`margin_used_usd`, existing copies
    plus anything already sent this cycle, plus this order at `exchange_lev`)
    stays <= `allocation_usd * ALLOCATION_SLACK`. Never negative."""
    cap = float(settings.allocation_usd or 0.0) * ALLOCATION_SLACK
    return max(0.0, cap - max(0.0, margin_used_usd)) * max(1, int(exchange_lev))


def open_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                   our_equity: float, n_leaders: int, exchange_lev: int,
                   his_gross_ntl_after: float = 0.0) -> float:
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
    - allocation: `allocation_notional` (needs `his_gross_ntl_after` for
      exposure_mode target; the default 0.0 sizes a target open at 0).
    """
    if settings.sizing_mode == SizingMode.allocation:
        return allocation_notional(settings, his_added_ntl, his_equity, his_gross_ntl_after,
                                   exchange_lev)
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
                  his_frac_added: float, his_gross_ntl_after: float = 0.0,
                  exchange_lev: Optional[int] = None) -> float:
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
    - allocation: `allocation_notional` with his INCREMENTAL notional, same
      formula as the open.

    Reduces, closes and flips never call this -- only an increase in the
    leader's absolute size does, in every sizing_mode.
    """
    if settings.sizing_mode == SizingMode.allocation:
        return allocation_notional(settings, his_added_ntl, his_equity, his_gross_ntl_after,
                                   exchange_lev)
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

    Exception: an `allocation` wallet in exposure_mode target always uses
    `settings.target_leverage`, capped the same way, whatever leverage_mode
    says, so its margin lands at about `allocation_usd`.
    """
    cap = max(1, min(int(coin_max), int(settings.max_position_leverage)))
    if (settings.sizing_mode == SizingMode.allocation
            and settings.exposure_mode == ExposureMode.target):
        return max(1, min(cap, int(settings.target_leverage)))
    if settings.leverage_mode == LeverageMode.match:
        return max(1, min(cap, math.ceil(his_lev)))
    if settings.leverage_mode == LeverageMode.fixed:
        return max(1, min(cap, int(settings.leverage)))
    return cap


def worse_entry_ok(side: str, mid: float, entry: float, pct: float) -> bool:
    """True when `mid` is within `pct` percent of the leader's own `entry`
    price (percent as in the contract: 10.0 = 10%) -- i.e. ok to open/add.

    A long is blocked once `mid > entry * (1 + pct/100)`; a short once
    `mid < entry * (1 - pct/100)`. `side` is OUR side (contract v8): a
    counter copy of his long is a short, checked against HIS entry, so it
    is blocked once mid has fallen more than pct below his entry (we would
    sell too cheap); a counter long (he is short) once mid has risen more
    than pct above it. `entry <= 0` (unknown/missing) always
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


def our_is_long(his_szi: float, direction: Any) -> bool:
    """Contract v8 TradeDirection: the side OUR copy takes for his signed size.
    copy: his side. counter: the opposite (he is long -> we are short).
    `direction` is a TradeDirection or its string value."""
    counter = getattr(direction, "value", direction) == "counter"
    return (his_szi > 0) != counter


def norm_coin(coin: str) -> str:
    """Coin key for the allow/block lists: case-insensitive, whitespace
    stripped. A HIP-3 coin keeps its "dex:COIN" form ("xyz:TSLA" and
    "XYZ:tsla" match each other, never plain "TSLA")."""
    return str(coin).strip().lower()


def coin_allowed(settings: Settings, coin: str) -> bool:
    """Contract v8 coin filters on the wallet's EFFECTIVE settings
    (`Settings.for_leader`: a wallet override's list replaces the book-wide
    one; absent = inherit). False when the allowlist is non-empty and the
    coin is not on it, or the coin is on the blocklist. Gates opens/adds
    only: exits are never filtered."""
    c = norm_coin(coin)
    allow = {norm_coin(x) for x in (settings.coin_allowlist or []) if str(x).strip()}
    if allow and c not in allow:
        return False
    block = {norm_coin(x) for x in (settings.coin_blocklist or []) if str(x).strip()}
    return c not in block


def bump_allowed(settings: Settings) -> bool:
    """Whether a sub-minimum open/add may be rounded up to the minimum.

    - small_account_mode skip: never, in any sizing mode.
    - allocation wallets: only in small_account_mode bump (concentrate
      handles small slices by dropping them and spreading the allocation
      over the rest instead, see `plan_allocation`). `min_order_bump` is
      not consulted: the Trade ticket's choice is the explicit one.
    - every other sizing mode: `min_order_bump` (the pre-v5 behavior;
      concentrate and bump both mean "as before" there).
    """
    if settings.small_account_mode == SmallAccountMode.skip:
        return False
    if settings.sizing_mode == SizingMode.allocation:
        return settings.small_account_mode == SmallAccountMode.bump
    return bool(settings.min_order_bump)


def bump(notional: float, settings: Settings) -> float:
    """Round a sub-floor notional up to `HL_MIN_ORDER_USD` when
    `bump_allowed(settings)` AND the notional is already at least
    `BUMP_FLOOR_FRAC` (25%) of the floor. Otherwise returns `notional`
    unchanged -- the caller is responsible for skipping it if it is still
    under the floor after this call. Already-adequate notionals pass
    through unchanged.
    """
    if notional >= HL_MIN_ORDER_USD:
        return notional
    if bump_allowed(settings) and notional >= BUMP_FLOOR_FRAC * HL_MIN_ORDER_USD:
        return HL_MIN_ORDER_USD
    return notional


def liq_distance_pct(leverage: int, is_cross: bool, maint_frac: float,
                     side: Optional[str] = None) -> float:
    """Adverse price-move percent, from entry, before liquidation.

    `side` given ("long" / "short"): HL's isolated formula (docs,
    "Liquidations": liq = entry - side x margin_available / size / (1 - m x side),
    margin_available = entry margin - maintenance), i.e.
    long `(1/L - m) / (1 - m)`, short `(1/L - m) / (1 + m)`. Maintenance is
    charged on the CURRENT notional, which shrinks as a long falls and grows
    as a short rises: a 1x long can never be liquidated (100%), a 1x short
    on a 3x-max coin is liquidated after +71%, not +83%.
    Regression: the discovery sim used the side-blind estimate below and
    liquidated 1x longs on low-max coins after an 83-90% drop.

    `side` None: the side-blind estimate `(1/leverage - maint_frac) * 100`. At 40x isolated with a 1.25% maintenance
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
    base = 1.0 / leverage - maint_frac
    if side == "long":
        base /= (1.0 - maint_frac)
    elif side == "short":
        base /= (1.0 + maint_frac)
    return max(0.0, base * 100.0)


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


# ── small accounts: the allocation plan (engine and Trade ticket preview) ────

def his_notional(pos: Mapping[str, Any]) -> float:
    """|size| x his average entry: the notional the engine sizes from
    (`_open_or_add` uses entry, not mark, for `his_added_ntl` too, so a
    plan and a live open always agree)."""
    try:
        return abs(float(pos.get("szi") or 0.0)) * float(pos.get("entry_px") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def gross_notional(positions: Mapping[str, Mapping[str, Any]]) -> float:
    """Sum of |notional| over a whole book (`his_notional` per coin)."""
    return sum(his_notional(p) for p in positions.values())


def concentrate(base: Mapping[str, float], ntl: Mapping[str, float], held: Iterable[str] = (),
                min_order: float = HL_MIN_ORDER_USD) -> "tuple[List[str], float]":
    """small_account_mode concentrate. `base[coin]` is the slice each of his
    positions gets un-concentrated, `ntl[coin]` his notional on it.

    Drops the smallest slice under `min_order` and renormalizes the rest
    (`scale = his gross / gross of what is left`, so the whole allocation
    goes into the positions that remain), one at a time, until every
    remaining slice clears the minimum. Dropping one at a time matters: a
    slice just under the floor can clear it once a smaller one is dropped.
    Coins in `held` (already copied) are never dropped: they stay copied
    until he exits. Ties drop the alphabetically first coin, so the result
    is deterministic. Returns `(eligible coins sorted, scale)`; nothing
    eligible -> `([], 1.0)`."""
    held_set = set(held)
    eligible = sorted(c for c in base if ntl.get(c, 0.0) > 0)
    gross = sum(ntl[c] for c in eligible)
    while eligible:
        e_gross = sum(ntl[c] for c in eligible)
        scale = gross / e_gross if e_gross > 0 else 1.0
        under = [c for c in eligible if c not in held_set and base[c] * scale < min_order]
        if not under:
            return eligible, scale
        eligible.remove(min(under, key=lambda c: (base[c] * scale, c)))
    return [], 1.0


def base_slices(ntl: Mapping[str, float], his_equity: float, allocation_usd: float,
                exposure_mode: ExposureMode, levs: Mapping[str, int]) -> Dict[str, float]:
    """Un-concentrated slice per coin for an allocation wallet, given his
    notional per coin: target `n / gross * allocation * lev`, match
    `n / his_equity * allocation` (0.0 on a zero denominator)."""
    gross = sum(v for v in ntl.values() if v > 0)
    out: Dict[str, float] = {}
    for c, n in ntl.items():
        if n <= 0:
            out[c] = 0.0
        elif exposure_mode == ExposureMode.target:
            out[c] = n / gross * allocation_usd * max(1, int(levs.get(c, 1))) if gross > 0 else 0.0
        else:
            out[c] = n / his_equity * allocation_usd if his_equity > 0 else 0.0
    return out


UNCAPPED_FALLBACK_USD = 50_000.0   # liquidity reads failed: only orders under this go out uncapped


def liquidity_cap(day_volume_usd: Optional[float], depth_usd: Optional[float],
                  max_order_volume_pct: float) -> Optional[float]:
    """Largest single order for a coin: min(max_order_volume_pct % of its
    24h volume, the book depth within the slippage cap). None when either
    read failed (the caller then applies `UNCAPPED_FALLBACK_USD`)."""
    if day_volume_usd is None or depth_usd is None:
        return None
    return max(0.0, min(float(max_order_volume_pct) / 100.0 * float(day_volume_usd),
                        float(depth_usd)))


def split_order(ntl: float, cap: Optional[float],
                min_order: float = HL_MIN_ORDER_USD) -> "tuple[float, float, Optional[str]]":
    """Split one open/add against the liquidity cap. Returns
    `(send_now, carry, skip_reason)`:

    - cap None (a liquidity read failed): the whole order if it is under
      `UNCAPPED_FALLBACK_USD`, else nothing with a reason.
    - ntl <= cap: the whole order.
    - cap under the exchange minimum: nothing, with a reason (pending).
    - otherwise `cap` now and `ntl - cap` carried to the next cycles; a
      carry under the minimum could never be placed, so it is dropped."""
    if cap is None:
        if ntl < UNCAPPED_FALLBACK_USD:
            return ntl, 0.0, None
        return 0.0, 0.0, (f"liquidity reads failed and ${ntl:,.2f} is over the "
                          f"${UNCAPPED_FALLBACK_USD:,.0f} uncapped limit")
    if ntl <= cap:
        return ntl, 0.0, None
    if cap < min_order:
        return 0.0, 0.0, f"liquidity cap ${cap:,.2f} is under the ${min_order} minimum"
    carry = ntl - cap
    return cap, (carry if carry >= min_order else 0.0), None


def fill_cycles(ntl: float, cap: Optional[float]) -> int:
    """Cycles a slice needs at one capped order per cycle (1 if uncapped)."""
    if cap is None or cap <= 0 or ntl <= cap:
        return 1
    return int(math.ceil(ntl / cap - 1e-9))


def plan_allocation(his_positions: Mapping[str, Mapping[str, Any]], his_equity: float,
                    allocation_usd: float, exposure_mode: ExposureMode, target_leverage: int,
                    small_account_mode: SmallAccountMode, coin_max_lev: Mapping[str, int], *,
                    lev_by_coin: Optional[Mapping[str, int]] = None, held: Iterable[str] = (),
                    liq_cap: Optional[Mapping[str, Optional[float]]] = None,
                    margin_used_usd: float = 0.0,
                    max_position_leverage: int = 50) -> Dict[str, Any]:
    """What an `allocation` wallet would copy of his book RIGHT NOW. Pure.
    The engine sizes every open from the same pieces (`allocation_notional`,
    `concentrate`, `allocation_room_ntl`, `bump`, `split_order`) in the same
    order, and the Trade ticket preview (`engine.public.preview_wallet`) is
    this function, so the preview is what the engine does.

    Per coin, in coin-name order (the order a first-sight batch is opened in):
      1. slice: target `n/gross * A * lev`, match `n/his_equity * A`
         (`n` = |size| x his entry, `lev` = exchange leverage for the coin).
      2. concentrate: coins outside `concentrate()`'s eligible set are
         skipped; the rest are multiplied by its scale.
      3. allocation cap: trimmed so total margin (`margin_used_usd` + slices
         so far + this one) stays <= A x ALLOCATION_SLACK.
      4. under $10.50: bump mode rounds up to it (if >= 25% of it and it
         still fits the cap), else skipped.
      5. liquidity: `liq_cap[coin]` (from `liquidity_cap`, None = read
         failed) gives `fill_cycles` or a liquidity skip.

    `lev_by_coin` (exact exchange leverage per coin, `exchange_leverage`)
    wins over `coin_max_lev`; without it target uses min(target_leverage,
    coin max, max_position_leverage) and match uses the coin max.

    `min_allocation_for_full_book`: the smallest allocation at which every
    one of his positions clears the minimum without concentrating.
    """
    alloc = max(0.0, float(allocation_usd))
    ntl = {c: his_notional(p) for c, p in his_positions.items()}
    ntl = {c: v for c, v in ntl.items() if v > 0}
    gross = sum(ntl.values())
    levs: Dict[str, int] = {}
    for c in ntl:
        if lev_by_coin and c in lev_by_coin:
            levs[c] = max(1, int(lev_by_coin[c]))
            continue
        cap = max(1, min(int(coin_max_lev.get(c, 1) or 1), int(max_position_leverage)))
        levs[c] = (max(1, min(cap, int(target_leverage))) if exposure_mode == ExposureMode.target
                   else cap)

    base = base_slices(ntl, his_equity, alloc, exposure_mode, levs)
    eligible, scale = list(ntl), 1.0
    if small_account_mode == SmallAccountMode.concentrate:
        eligible, scale = concentrate(base, ntl, held)
    eligible_set = set(eligible)
    bump_ok = small_account_mode == SmallAccountMode.bump
    cap_total = alloc * ALLOCATION_SLACK
    used = max(0.0, float(margin_used_usd))
    slices: List[Dict[str, Any]] = []
    for c in sorted(ntl):
        lev = levs[c]
        szi = float(his_positions[c].get("szi") or 0.0)
        row: Dict[str, Any] = {
            "coin": c, "side": "long" if szi > 0 else "short",
            "his_notional_usd": ntl[c], "weight_pct": ntl[c] / gross * 100.0 if gross else 0.0,
            "leverage": lev, "notional_usd": 0.0, "margin_usd": 0.0, "status": "copy",
            "reason": None, "liquidity_cap_usd": None, "fill_cycles": 1,
        }
        slices.append(row)
        if c not in eligible_set:
            row["status"] = "skip"
            row["reason"] = (f"concentrate: slice ${base[c] * scale:,.2f} under the "
                             f"${HL_MIN_ORDER_USD} minimum, allocation goes to his bigger positions")
            continue
        s = base[c] * scale
        room = max(0.0, cap_total - used) * lev
        if s > room:
            s, row["status"] = room, "trimmed"
        if s < HL_MIN_ORDER_USD:
            if (bump_ok and s >= BUMP_FLOOR_FRAC * HL_MIN_ORDER_USD
                    and used + HL_MIN_ORDER_USD / lev <= cap_total + 1e-9):
                s, row["status"] = HL_MIN_ORDER_USD, "bump"
            else:
                row["status"] = "skip"
                row["reason"] = (f"allocation full (margin ${used:,.2f} of ${cap_total:,.2f})"
                                 if row["status"] == "trimmed" else f"slice ${s:,.2f} under the ${HL_MIN_ORDER_USD} minimum")
                continue
        if liq_cap is not None:
            cap = liq_cap.get(c)
            row["liquidity_cap_usd"] = cap
            send, _carry, why = split_order(s, cap)
            if why:
                row["status"], row["reason"] = "skip", why
                continue
            row["fill_cycles"] = fill_cycles(s, cap)
        row["notional_usd"] = s
        row["margin_usd"] = s / lev
        used += s / lev

    if exposure_mode == ExposureMode.target:
        needs = [HL_MIN_ORDER_USD / (ntl[c] / gross * levs[c]) for c in ntl] if gross > 0 else []
    else:
        needs = [HL_MIN_ORDER_USD * his_equity / ntl[c] for c in ntl] if his_equity > 0 else []
    min_full = math.ceil(max(needs) * 100 - 1e-6) / 100.0 if needs else None
    copied = [r for r in slices if r["status"] != "skip"]
    return {
        "slices": slices,
        "scale": scale,
        "planned_notional_usd": sum(r["notional_usd"] for r in copied),
        "planned_margin_usd": sum(r["margin_usd"] for r in copied),
        "copied": [r["coin"] for r in copied],
        "skipped": [r["coin"] for r in slices if r["status"] == "skip"],
        "min_allocation_for_full_book": min_full,
        "multi_cycle": any(r["fill_cycles"] > 1 for r in copied),
    }


def plan_copy(settings: Settings, his_positions: Mapping[str, Mapping[str, Any]],
              his_equity: float, coin_max_lev: Mapping[str, int], *,
              our_equity: Optional[float] = None, n_leaders: int = 1,
              lev_by_coin: Optional[Mapping[str, int]] = None,
              liq_cap: Optional[Mapping[str, Optional[float]]] = None,
              open_copies: int = 0,
              taken: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """`plan_allocation`'s sibling for the other sizing modes (fixed_margin,
    fixed_notional, proportional): what a first sight of his book would open
    under `settings` (a global wallet runs on the Settings tab as-is). Same
    result shape, so one preview renders both. Pure.

    Per coin, in coin-name order (the engine's first-sight order):
      - `taken[coin]` (another wallet owns our copy of it): skipped.
      - `max_open_copies`: opens past it (counting `open_copies` already
        open across all wallets) are skipped.
      - notional `open_notional(settings, his notional, his_equity,
        our_equity, n_leaders, lev)` at `lev_by_coin` (else the coin max
        capped by max_position_leverage); proportional needs `our_equity`.
      - `bump` (min_order_bump / small_account_mode), then the $10.50 floor.
      - liquidity: `split_order` / `fill_cycles` as in `plan_allocation`.
    Not modelled: our free margin (room cap) and price moves."""
    ntl = {c: his_notional(p) for c, p in his_positions.items()}
    ntl = {c: v for c, v in ntl.items() if v > 0}
    gross = sum(ntl.values())
    taken = taken or {}
    opened = 0
    slices: List[Dict[str, Any]] = []
    for c in sorted(ntl):
        if lev_by_coin and c in lev_by_coin:
            lev = max(1, int(lev_by_coin[c]))
        else:
            lev = max(1, min(int(coin_max_lev.get(c, 1) or 1), int(settings.max_position_leverage)))
        szi = float(his_positions[c].get("szi") or 0.0)
        row: Dict[str, Any] = {
            "coin": c, "side": "long" if szi > 0 else "short",
            "his_notional_usd": ntl[c], "weight_pct": ntl[c] / gross * 100.0 if gross else 0.0,
            "leverage": lev, "notional_usd": 0.0, "margin_usd": 0.0, "status": "copy",
            "reason": None, "liquidity_cap_usd": None, "fill_cycles": 1,
        }
        slices.append(row)
        if c in taken:
            row["status"], row["reason"] = "skip", f"owned by wallet {taken[c]}"
            continue
        if open_copies + opened >= settings.max_open_copies:
            row["status"] = "skip"
            row["reason"] = f"max_open_copies reached ({settings.max_open_copies})"
            continue
        if settings.sizing_mode == SizingMode.proportional and our_equity is None:
            row["status"], row["reason"] = "skip", "our equity unknown (engine status unavailable)"
            continue
        s = open_notional(settings, ntl[c], his_equity, float(our_equity or 0.0),
                          max(1, n_leaders), lev)
        bumped = bump(s, settings)
        if bumped != s:
            row["status"] = "bump"
        s = bumped
        if s < HL_MIN_ORDER_USD:
            row["status"] = "skip"
            row["reason"] = f"copy ${s:,.2f} under the ${HL_MIN_ORDER_USD} minimum"
            continue
        if liq_cap is not None:
            cap = liq_cap.get(c)
            row["liquidity_cap_usd"] = cap
            _send, _carry, why = split_order(s, cap)
            if why:
                row["status"], row["reason"] = "skip", why
                continue
            row["fill_cycles"] = fill_cycles(s, cap)
        row["notional_usd"] = s
        row["margin_usd"] = s / lev
        opened += 1
    copied = [r for r in slices if r["status"] != "skip"]
    return {
        "slices": slices,
        "scale": 1.0,
        "planned_notional_usd": sum(r["notional_usd"] for r in copied),
        "planned_margin_usd": sum(r["margin_usd"] for r in copied),
        "copied": [r["coin"] for r in copied],
        "skipped": [r["coin"] for r in slices if r["status"] == "skip"],
        "min_allocation_for_full_book": None,
        "multi_cycle": any(r["fill_cycles"] > 1 for r in copied),
    }



def fixed_copy_cap_ntl(settings: Settings, exchange_lev: int) -> Optional[float]:
    """Largest notional ONE copy may reach in a fixed sizing mode, or None for
    the other modes (allocation has its own wallet-level cap, proportional
    tracks his book). The $10.50 floor is included because an open may have
    been bumped to it; 2% slack absorbs size rounding."""
    if settings.sizing_mode == SizingMode.fixed_margin:
        base = settings.fixed_margin_usd * max(1, int(exchange_lev))
    elif settings.sizing_mode == SizingMode.fixed_notional:
        base = settings.fixed_notional_usd
    else:
        return None
    return max(base, HL_MIN_ORDER_USD) * 1.02
