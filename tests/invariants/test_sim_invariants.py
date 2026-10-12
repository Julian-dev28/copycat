"""Copy-sim invariants (discovery.sim on the real engine.sizing).

Random leader books (opens / adds / reduces / closes on 1-3 coins) over
random 1m candle paths; each test re-runs the SAME fills and candles under
different settings and checks a relation that must hold between the runs.
"""
from __future__ import annotations

import math

from discovery.candles_cache import Series
from discovery.positions import PositionEvent
from discovery.sim import FALLBACK_SLIPPAGE_BPS, SLIPPAGE_BPS, TAKER_FEE_RATE, simulate_wallet
from engine import sizing as real_sizing
from hypothesis import assume, given
from hypothesis import strategies as st

from contracts.models import (
    LeaderOverride,
    LeverageMode,
    MarginMode,
    Settings,
    SizingMode,
)

M = 60_000
COINS = ["BTC", "ETH", "SOL"]


@st.composite
def world(draw, max_move=0.6):
    """(events, series, coin_max, end_ms). Prices: a bounded random walk, so
    no candle is ever more than `max_move` away from the first price."""
    n_bars = draw(st.integers(30, 120))
    coins = draw(st.lists(st.sampled_from(COINS), min_size=1, max_size=3, unique=True))
    series, events, coin_max = {}, [], {}
    for c in coins:
        p0 = draw(st.sampled_from([0.5, 20.0, 3_000.0, 60_000.0]))
        steps = draw(st.lists(st.floats(-0.08, 0.08), min_size=n_bars, max_size=n_bars))
        wick = draw(st.floats(0.0, 0.03))
        s = Series()
        px, closes = p0, []
        for i, r in enumerate(steps):
            o = px
            px = min(p0 * (1 + max_move), max(p0 * (1 - max_move), px * (1 + r)))
            hi = min(p0 * (1 + max_move), max(o, px) * (1 + wick))
            lo = max(p0 * (1 - max_move), min(o, px) * (1 - wick))
            s.append(i * M, M, o, hi, lo, px)
            closes.append(px)
        series[c] = s
        coin_max[c] = draw(st.sampled_from([10, 20, 40, 50]))
        # one leader trip per coin: open, then adds / reduces, then (maybe) close
        t = draw(st.integers(0, n_bars // 3))
        side = draw(st.sampled_from(["long", "short"]))
        size = draw(st.floats(1.0, 100.0)) * 1_000.0 / p0
        pos = 0.0

        def ev(kind, d, t_bar):
            nonlocal pos
            start = pos
            pos = pos + d if kind in ("open", "add") else max(0.0, pos - d)
            sgn = 1 if side == "long" else -1
            events.append(PositionEvent(coin=c, time_ms=t_bar * M + 5_000, kind=kind, side=side,
                                        delta_sz=d, start_position=sgn * start, end_position=sgn * pos,
                                        px=closes[t_bar]))
        ev("open", size, t)
        for _ in range(draw(st.integers(0, 4))):
            t += draw(st.integers(1, 10))
            if t >= n_bars - 1:
                break
            if draw(st.booleans()):
                ev("add", size * draw(st.floats(0.05, 1.0)), t)
            else:
                ev("reduce", pos * draw(st.floats(0.05, 0.6)), t)
        t += draw(st.integers(1, 10))
        if t < n_bars - 1 and draw(st.booleans()):
            ev("close", pos, t)
    events.sort(key=lambda e: (e.time_ms, e.coin))
    return events, series, coin_max, n_bars * M


def base_settings(**kw) -> Settings:
    d = dict(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=200.0, leverage_mode=LeverageMode.fixed,
             leverage=5, max_position_leverage=50, margin_mode=MarginMode.isolated, max_worse_entry_pct=100.0,
             min_order_bump=True, max_open_copies=50)
    d.update(kw)
    return Settings(**d)


def sim(w, s: Settings, equity=100_000.0, his_equity=1_000_000.0, curve=False):
    events, series, coin_max, end = w
    return simulate_wallet(events=events, series=series, coin_max_lev=coin_max, leader_equity_usd=his_equity,
                           leader_leverage_by_coin={c: 10.0 for c in coin_max}, settings=s,
                           sim_equity_usd=equity, window_end_ms=end, sizing=real_sizing,
                           curve_step_ms=10 * M if curve else None, window_start_ms=0 if curve else None)


MODES = st.sampled_from([SizingMode.fixed_notional, SizingMode.fixed_margin, SizingMode.proportional,
                         SizingMode.allocation])


@given(world(max_move=0.85), MODES, st.sampled_from(list(MarginMode)))
def test_1x_never_liquidates_without_a_90pct_adverse_move(w, mode, mm):
    """Prevents: the motivating bug class, '2 liquidations at fixed 1x'. HL's
    isolated formula puts a 1x long's liquidation at a price of 0 and a 1x
    short's at +(1-m)/(1+m) >= +90.5% on a coin whose max is >= 10. Paths here
    never rise 85% above any leader fill, so a 1x copy must never be
    liquidated, in any sizing mode, isolated or cross."""
    s = base_settings(sizing_mode=mode, leverage=1, fixed_margin_usd=50.0, allocation_usd=5_000.0,
                      target_leverage=1)
    events, series, *_ = w
    for e in events:
        assume(max(series[e.coin].h) <= e.px * 1.85)
    r = sim(w, s.model_copy(update={"margin_mode": mm}))
    assert r.sim_liquidations == 0, r.flags


@given(world())
def test_liquidations_monotone_in_leverage(w):
    """Prevents: a what-if where LOWER leverage shows MORE liquidations on the
    same fills and candles (e.g. the saved 20x and a 1x override swapped, or a
    liq price that moves the wrong way). Fixed notional: size is the same at
    every leverage, only margin and liq distance change. Ties allowed."""
    liqs = [sim(w, base_settings(leverage=lev)).sim_liquidations for lev in (1, 2, 3, 5, 10, 20, 40)]
    assert all(a <= b for a, b in zip(liqs, liqs[1:])), liqs


@given(world(), st.floats(11.0, 400.0))
def test_fees_non_negative_and_grow_with_turnover(w, ntl):
    """Prevents: negative fees (a rebate the copier never gets) and fees that
    shrink when the copy trades MORE notional. Fees are exactly the taker rate
    on every open/add/reduce/close notional, so doubling the size (no bumps,
    same liquidations) doubles them."""
    a = sim(w, base_settings(fixed_notional_usd=ntl))
    b = sim(w, base_settings(fixed_notional_usd=2 * ntl))
    assert a.sim_fees_usd >= 0 and b.sim_fees_usd >= 0
    assert b.sim_fees_usd >= a.sim_fees_usd - 1e-9
    if a.sim_liquidations == b.sim_liquidations and a.sim_skipped_min_order == b.sim_skipped_min_order == 0:
        assert math.isclose(b.sim_fees_usd, 2 * a.sim_fees_usd, rel_tol=0.08), (a, b)


@given(world(max_move=0.3))
def test_counter_return_is_minus_copy_minus_costs(w):
    """Prevents: a counter what-if that is not the mirror of the copy (a side
    not inverted somewhere: PnL, mark, liq). On flat funding and at 1x (no
    liquidations), ret_counter ~= -ret_copy - both runs' fees - slippage paid
    on both sides; slippage is bounded by the turnover x 2 x the worst bps."""
    copy = sim(w, base_settings(leverage=1))
    ctr = sim(w, base_settings(leverage=1, trade_direction="counter"))
    assume(copy.sim_liquidations == ctr.sim_liquidations == 0)
    assert copy.sim_copies == ctr.sim_copies
    eq = 100_000.0
    fees_pct = (copy.sim_fees_usd + ctr.sim_fees_usd) / eq * 100
    turnover = copy.sim_fees_usd / TAKER_FEE_RATE
    slip_pct = turnover * 2 * max(SLIPPAGE_BPS, FALLBACK_SLIPPAGE_BPS) / 1e4 * 1.6 / eq * 100
    gap = ctr.sim_return_pct - (-copy.sim_return_pct - fees_pct)
    assert -slip_pct - 1e-9 <= gap <= 1e-9, (gap, slip_pct, fees_pct)


@given(world(), st.sampled_from([1, 2, 3, 5, 10, 20, 40]), st.sampled_from([1, 2, 3, 5, 10, 20, 40]))
def test_what_if_override_changes_result_iff_terms_change(w, saved_lev, new_lev):
    """Prevents: the motivating bug. A what-if at fixed 1x returned the SAME
    result as the saved settings. Fixed margin sizes notional = margin x
    leverage, so changing the effective leverage must change the result when
    anything was copied; an override that leaves the effective terms equal
    (same leverage, or a `leverage` while leverage_mode is max) must not."""
    saved = base_settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=20.0, leverage=saved_lev)
    o = LeaderOverride(leverage_mode=LeverageMode.fixed, leverage=new_lev)
    eff = saved.model_copy(update={k: v for k, v in o.model_dump().items() if v is not None})
    a, b = sim(w, saved), sim(w, eff)
    levs_a = {c: real_sizing.exchange_leverage(saved, 10.0, m) for c, m in w[2].items()}
    levs_b = {c: real_sizing.exchange_leverage(eff, 10.0, m) for c, m in w[2].items()}
    key = lambda r: (round(r.sim_return_pct, 9), round(r.sim_fees_usd, 9), r.sim_liquidations)  # noqa: E731
    if levs_a == levs_b:
        assert key(a) == key(b)
    elif a.sim_copies and b.sim_copies:
        assert key(a) != key(b)
    # leverage_mode max ignores `leverage`: the override is a no-op
    m = base_settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=20.0, leverage_mode=LeverageMode.max)
    assert key(sim(w, m)) == key(sim(w, m.model_copy(update={"leverage": new_lev})))


@given(world(), MODES)
def test_curve_start_drawdown_and_return_agree(w, mode):
    """Prevents: an equity chart that does not start at the sim equity, a
    positive 'drawdown', or a headline return that disagrees with the
    curve's own last point."""
    eq = 10_000.0
    r = sim(w, base_settings(sizing_mode=mode, fixed_margin_usd=20.0, allocation_usd=2_000.0), equity=eq,
            curve=True)
    assert r.curve[0][1] == eq
    assert r.sim_max_drawdown_pct <= 0.0
    assert math.isclose(r.curve[-1][1] / eq * 100 - 100, r.sim_return_pct, abs_tol=1e-6)
    lo = min(v for _, v in r.curve)
    assert r.sim_max_drawdown_pct <= (lo / eq - 1) * 100 + 1e-6 or lo >= eq


@given(world(), st.lists(st.sampled_from(COINS), max_size=2))
def test_coin_filter_removes_exactly_those_coins(w, block):
    """Prevents: a blocked coin still traded in the what-if, or the block
    also dropping other coins. Blocking = the same run on the event list
    without those coins' opens (fixed notional, no shared caps bind)."""
    events, series, cm, end = w
    a = sim(w, base_settings(coin_blocklist=block))
    kept = [e for e in events if e.coin not in block]
    b = sim((kept, series, cm, end), base_settings())
    assert (a.sim_copies, round(a.sim_return_pct, 9), round(a.sim_fees_usd, 9)) == \
        (b.sim_copies, round(b.sim_return_pct, 9), round(b.sim_fees_usd, 9))
    assert not any(f == f"liquidated:{c}" for f in a.flags for c in block)
