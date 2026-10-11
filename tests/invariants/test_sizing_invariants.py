"""Sizing invariants (engine.sizing): the numbers every other path reuses.

Each test's docstring names the wrong number it prevents.
"""
from __future__ import annotations

import math

from engine import sizing
from hypothesis import assume, given
from hypothesis import strategies as st

from contracts.models import (
    HL_MIN_ORDER_USD,
    ExposureMode,
    LeverageMode,
    Settings,
    SizingMode,
    SmallAccountMode,
)

COINS = ["AAA", "BTC", "ETH", "SOL", "xyz:TSLA", "ZZZ"]
COIN_MAX = st.sampled_from([3, 5, 10, 20, 25, 40, 50])
LEV = st.integers(1, 50)


@st.composite
def books(draw, min_size=1, max_size=6):
    coins = draw(st.lists(st.sampled_from(COINS), min_size=min_size, max_size=max_size, unique=True))
    out = {}
    for c in coins:
        ntl = draw(st.floats(10.0, 5_000_000.0))
        px = draw(st.floats(0.01, 100_000.0))
        side = draw(st.sampled_from([1.0, -1.0]))
        out[c] = {"szi": side * ntl / px, "entry_px": px, "lev": float(draw(st.integers(1, 50)))}
    return out


@st.composite
def any_settings(draw):
    return Settings(
        sizing_mode=draw(st.sampled_from(list(SizingMode))),
        fixed_margin_usd=draw(st.floats(0.01, 5_000.0)),
        fixed_notional_usd=draw(st.floats(HL_MIN_ORDER_USD, 50_000.0)),
        size_multiplier=draw(st.floats(0.0, 10.0)),
        leverage_mode=draw(st.sampled_from(list(LeverageMode))),
        leverage=draw(LEV), max_position_leverage=draw(LEV), target_leverage=draw(LEV),
        allocation_usd=draw(st.floats(0.0, 100_000.0)),
        exposure_mode=draw(st.sampled_from(list(ExposureMode))),
        small_account_mode=draw(st.sampled_from(list(SmallAccountMode))),
        min_order_bump=draw(st.booleans()),
        max_open_copies=draw(st.integers(1, 50)),
    )


@given(any_settings(), st.floats(0.0, 100.0), COIN_MAX)
def test_effective_leverage_never_exceeds_any_cap(s, his_lev, coin_max):
    """Prevents: a copy opened at a leverage above the user's own cap, the coin
    max, or (fixed / target) the leverage the user picked. The wrong number:
    a 20x position on a ticket that said 5x."""
    lev = sizing.exchange_leverage(s, his_lev, coin_max)
    assert 1 <= lev <= max(1, min(coin_max, s.max_position_leverage))
    if s.sizing_mode == SizingMode.allocation and s.exposure_mode == ExposureMode.target:
        assert lev <= s.target_leverage
    elif s.leverage_mode == LeverageMode.fixed:
        assert lev <= s.leverage
    elif s.leverage_mode == LeverageMode.match:
        assert lev <= max(1, math.ceil(his_lev))


@given(COIN_MAX, st.sampled_from(["long", "short", None]), st.booleans())
def test_liq_distance_decreases_with_leverage_and_is_wide_at_1x(coin_max, side, cross):
    """Prevents: a liquidation price that gets FARTHER away as leverage goes up
    (inverted risk display / sim), and a 1x copy that liquidates on an ordinary
    move. At 1x on a coin whose max is >= 20 the adverse move needed is >= 95%;
    a 1x long can only liquidate at a price of ~0 (HL's isolated formula)."""
    m = 1.0 / (2.0 * coin_max)
    d = [sizing.liq_distance_pct(lev, cross, m, side=side) for lev in range(1, coin_max + 1)]
    assert all(a >= b for a, b in zip(d, d[1:]))
    assert all(a > b for a, b in zip(d, d[1:]) if b > 0)
    if coin_max >= 20:
        assert d[0] >= 95.0
    if side == "long":
        assert d[0] >= 99.999
    if side is not None:
        # never farther than the plain (1/L - m) estimate for a short, never closer for a long
        plain = [sizing.liq_distance_pct(lev, cross, m) for lev in range(1, coin_max + 1)]
        for got, p in zip(d, plain):
            assert (got >= p - 1e-9) if side == "long" else (got <= p + 1e-9)


def _check_plan_rows(plan, lev_bound=None):
    for r in plan["slices"]:
        if r["status"] == "skip":
            assert r["notional_usd"] == 0.0 and r["margin_usd"] == 0.0
            continue
        assert r["notional_usd"] >= HL_MIN_ORDER_USD - 1e-9, r
        assert math.isclose(r["margin_usd"], r["notional_usd"] / r["leverage"], rel_tol=1e-12)
        if lev_bound is not None:
            assert r["leverage"] <= lev_bound[r["coin"]]
    live = [r for r in plan["slices"] if r["status"] != "skip"]
    assert math.isclose(plan["planned_margin_usd"], sum(r["margin_usd"] for r in live), rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(plan["planned_notional_usd"], sum(r["notional_usd"] for r in live), rel_tol=1e-9,
                        abs_tol=1e-9)


@given(books(), st.floats(100.0, 50_000_000.0), st.floats(1.0, 50_000.0), st.sampled_from(list(ExposureMode)),
       LEV, st.sampled_from(list(SmallAccountMode)), st.dictionaries(st.sampled_from(COINS), COIN_MAX),
       st.floats(0.0, 2_000.0), LEV)
def test_plan_allocation_cap_floor_and_margin(book, his_eq, alloc, exp, tl, sam, maxes, used, mpl):
    """Prevents: (1) an allocation wallet holding more margin than the user
    invested (cap = allocation x 1.02 incl. margin already used), (2) a
    concentrate/bump/skip slice under HL's $10.50 minimum shown as 'copy'
    (the engine would never place it), (3) margin != notional / leverage on a
    preview row, (4) planned totals that do not add up to the rows."""
    cm = {c: maxes.get(c, 50) for c in book}
    plan = sizing.plan_allocation(book, his_eq, alloc, exp, tl, sam, cm, margin_used_usd=used,
                                  max_position_leverage=mpl)
    _check_plan_rows(plan, {c: max(1, min(cm[c], mpl)) for c in book})
    assert used + plan["planned_margin_usd"] <= max(used, alloc * sizing.ALLOCATION_SLACK) + 1e-6


@given(books(), st.floats(100.0, 50_000_000.0), any_settings(), st.dictionaries(st.sampled_from(COINS), COIN_MAX),
       st.floats(10.0, 1_000_000.0), st.integers(0, 10))
def test_plan_copy_floor_margin_and_open_cap(book, his_eq, s, maxes, our_eq, open_now):
    """Prevents: a fixed/proportional preview row under $10.50 marked as copied,
    margin != notional / leverage, and a preview that opens more copies than
    max_open_copies allows."""
    assume(s.sizing_mode != SizingMode.allocation)
    cm = {c: maxes.get(c, 50) for c in book}
    plan = sizing.plan_copy(s, book, his_eq, cm, our_equity=our_eq, open_copies=open_now)
    _check_plan_rows(plan)
    assert len(plan["copied"]) <= max(0, s.max_open_copies - open_now)


@given(any_settings(), st.floats(0.0, 1e6), st.floats(0.0, 1e7), st.floats(0.0, 1e7), st.floats(0.0, 1e7), LEV)
def test_bump_never_lands_between_floor_frac_and_min(s, ntl, a, b, c, lev):
    """Prevents: a 'bumped' order that is still under the exchange minimum, or a
    bump that shrinks an order. bump() returns the input or exactly $10.50."""
    out = sizing.bump(ntl, s)
    assert out >= ntl
    assert out == ntl or out == HL_MIN_ORDER_USD


@given(any_settings(), LEV, st.lists(st.floats(0.0, 2.0), min_size=1, max_size=40),
       st.floats(1.0, 100_000.0))
def test_fixed_cap_holds_through_any_add_sequence(s, lev, fracs, px):
    """Prevents: the 'DRAM' bug class. A fixed-size copy topped up by dozens of
    tiny adds (each bumped to $10.50) growing to many times its fixed size.
    Replays the engine's add rule (add_notional -> cap to fixed_copy_cap_ntl -
    held -> bump -> refuse if the bump passes the cap) over any sequence."""
    assume(s.sizing_mode in (SizingMode.fixed_margin, SizingMode.fixed_notional))
    cap = sizing.fixed_copy_cap_ntl(s, lev)
    held = sizing.bump(sizing.open_notional(s, 1000.0, 1e6, 1e4, 1, lev), s)
    if held < HL_MIN_ORDER_USD:
        return
    assert held <= cap + 1e-9
    for f in fracs:
        add = sizing.add_notional(s, 0.0, 1e6, 1e4, 1, held, f)
        allowed = max(0.0, cap - held)
        if allowed < HL_MIN_ORDER_USD:
            continue
        add = sizing.bump(min(add, allowed), s)
        if add > allowed + 1e-9 or add < HL_MIN_ORDER_USD:
            continue
        held += add
        assert held <= cap + 1e-6


@given(st.floats(-1e6, 1e6).filter(lambda x: x != 0))
def test_counter_is_copy_inverted(szi):
    """Prevents: a counter copy that ends up on HIS side (doubling his bet
    instead of fading it)."""
    assert sizing.our_is_long(szi, "copy") == (szi > 0)
    assert sizing.our_is_long(szi, "counter") == (szi < 0)


@given(st.lists(st.sampled_from(COINS + [" btc", "XYZ:tsla", "Eth "]), max_size=4),
       st.lists(st.sampled_from(COINS + [" btc", "XYZ:tsla"]), max_size=4), st.sampled_from(COINS))
def test_coin_filter_removes_exactly_those_coins(allow, block, coin):
    """Prevents: a blocked coin still copied, or an allowed coin dropped
    (case / whitespace / HIP-3 prefix mismatch)."""
    s = Settings(coin_allowlist=allow, coin_blocklist=block)
    a = {x.strip().lower() for x in allow}
    b = {x.strip().lower() for x in block}
    c = coin.lower()
    assert sizing.coin_allowed(s, coin) == ((not a or c in a) and c not in b)
