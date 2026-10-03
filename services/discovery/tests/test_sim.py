"""Copy-sim tests against the REAL engine.sizing (pure, no I/O), so they
prove the sim obeys the live engine's rules, not a reimplementation."""
from __future__ import annotations

import pytest
from engine import sizing as real_sizing

from contracts.models import HL_MIN_ORDER_USD, LeverageMode, MarginMode, Settings, SizingMode
from discovery.candles_cache import Series
from discovery.positions import PositionEvent
from discovery.sim import FALLBACK_SLIPPAGE_BPS, SLIPPAGE_BPS, TAKER_FEE_RATE, simulate_wallet

from discovery_fakes import flat_candles

M = 60_000


def evt(coin, time_ms, kind, side, delta_sz, start, end, px):
    return PositionEvent(coin=coin, time_ms=time_ms, kind=kind, side=side, delta_sz=delta_sz,
                         start_position=start, end_position=end, px=px)


def series(rows, step=M) -> Series:
    s = Series()
    for r in rows:
        s.append(r["t"], step, r["o"], r["h"], r["l"], r["c"])
    return s


def run(events, ser, settings, equity=1000.0, end_ms=420_000, max_lev=50, trace=None):
    coins = {e.coin for e in events}
    return simulate_wallet(events=events, series=ser, coin_max_lev={c: max_lev for c in coins},
                           leader_equity_usd=1_000_000.0, leader_leverage_by_coin={}, settings=settings,
                           sim_equity_usd=equity, window_end_ms=end_ms, sizing=real_sizing, trace=trace)


def fixed(ntl=20.0, lev=5, **kw):
    return Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=ntl, leverage_mode=LeverageMode.fixed,
                    leverage=lev, max_position_leverage=50, margin_mode=MarginMode.isolated,
                    max_worse_entry_pct=50.0, min_order_bump=True, **kw)


def test_open_add_reduce_close_mechanics_and_fee_accounting():
    events = [
        evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0),
        evt("BTC", 120_000, "add", "long", 0.5, 1.0, 1.5, 102.0),
        evt("BTC", 240_000, "reduce", "long", 0.75, 1.5, 0.75, 98.0),
        evt("BTC", 360_000, "close", "long", 0.75, 0.75, 0.0, 101.0),
    ]
    r = run(events, {"BTC": series(flat_candles(0, 420_000, 100.0))}, fixed())
    assert r.sim_copies == 1 and r.sim_liquidations == 0 and r.sim_skipped_min_order == 0
    # open=20, add 10 bumped to 10.5, reduce half of 30.5, close the rest
    assert r.sim_fees_usd == pytest.approx(TAKER_FEE_RATE * (20.0 + 10.5 + 15.25 + 15.25), rel=1e-6)
    assert -0.1 < r.sim_return_pct < 0
    assert -0.1 < r.sim_max_drawdown_pct <= 0


def test_exec_price_is_next_1m_open_plus_slippage():
    lines = []
    rows = flat_candles(0, 300_000, 100.0)
    rows[1]["o"] = 101.0   # the bar right after the fill at t=10s
    run([evt("BTC", 10_000, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(rows)}, fixed(),
        end_ms=300_000, trace=lines.append)
    assert f"px={101.0 * (1 + SLIPPAGE_BPS / 1e4):.6g}" in lines[0]


def test_exec_price_falls_back_to_his_fill_when_no_1m_bar():
    """Regression (coordinator bug 2): with no 1m bar right after his fill,
    the old code took the FIRST later candle, days later, as our entry."""
    lines = []
    late = [{"t": 3 * 86_400_000, "o": 500.0, "h": 500.0, "l": 500.0, "c": 500.0}]
    run([evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(late, 900_000)}, fixed(),
        end_ms=4 * 86_400_000, trace=lines.append)
    assert f"px={100.0 * (1 + FALLBACK_SLIPPAGE_BPS / 1e4):.6g}" in lines[0]


def test_one_liquidation_loses_only_that_copys_margin_even_on_a_gap():
    """Regression (coordinator bug 2: -99.9% from ONE xyz:DRAM liquidation at
    $100 equity, fixed_margin $1). A price that gaps far past the liq price
    with no wick in our data must cost the posted margin, never more."""
    s = Settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=1.0, leverage_mode=LeverageMode.max,
                 margin_mode=MarginMode.isolated)
    rows = flat_candles(0, 120_000, 100.0)
    rows.append({"t": 86_400_000, "o": 10.0, "h": 10.0, "l": 10.0, "c": 10.0})   # -90% after a data gap
    r = run([evt("xyz:DRAM", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"xyz:DRAM": series(rows)}, s,
            equity=100.0, end_ms=2 * 86_400_000, max_lev=10)
    assert r.sim_liquidations == 1
    margin = 1.0                          # fixed_margin 1 x 10x lev = $10 -> bumped to $10.50 notional
    ntl = HL_MIN_ORDER_USD
    assert r.sim_return_pct == pytest.approx(-(ntl / 10 + ntl * TAKER_FEE_RATE), abs=1e-6)
    assert r.sim_return_pct > -1.2 and margin == 1.0


def test_liquidation_triggers_on_adverse_wick():
    rows = flat_candles(0, 300_000, 100.0)
    rows[3]["l"] = 98.0
    r = run([evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(rows)},
            fixed(HL_MIN_ORDER_USD, 50), equity=100.0, end_ms=300_000)
    assert r.sim_liquidations == 1
    assert any(f.startswith("liquidated:BTC") for f in r.flags)


def test_wick_in_the_bar_that_started_before_the_open_is_not_checked():
    rows = flat_candles(0, 300_000, 100.0)
    rows[0]["l"] = 50.0          # bar [0, 60s) started before our open at t=30s
    r = run([evt("BTC", 30_000, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(rows)},
            fixed(HL_MIN_ORDER_USD, 50), equity=100.0, end_ms=300_000)
    assert r.sim_liquidations == 0


def test_15m_bars_check_liquidation_too():
    rows = flat_candles(0, 10 * 900_000, 100.0, step_ms=900_000)
    rows[4]["l"] = 97.0
    r = run([evt("ETH", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"ETH": series(rows, 900_000)},
            fixed(HL_MIN_ORDER_USD, 50), equity=100.0, end_ms=10 * 900_000)
    assert r.sim_liquidations == 1


def test_drawdown_reflects_intratrade_dip():
    rows = flat_candles(0, 300_000, 100.0)
    for row in rows:
        if 120_000 <= row["t"] <= 180_000:
            row["o"] = row["h"] = row["l"] = row["c"] = 90.0
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0),
              evt("BTC", 240_000, "close", "long", 1.0, 1.0, 0.0, 100.0)]
    r = run(events, {"BTC": series(rows)}, fixed(50.0, 5), end_ms=300_000)
    assert r.sim_liquidations == 0
    assert r.sim_max_drawdown_pct < -0.3
    assert r.sim_return_pct > -0.3


def test_sub_bump_floor_is_skipped_and_bump_rounds_up():
    s1 = Settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=0.10, leverage_mode=LeverageMode.fixed,
                  leverage=10, max_worse_entry_pct=50.0)
    r1 = run([evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(flat_candles(0, 60_000, 100.0))},
             s1, end_ms=60_000)
    assert r1.sim_copies == 0 and r1.sim_skipped_min_order == 1
    s2 = s1.model_copy(update={"fixed_margin_usd": 0.30})
    r2 = run([evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {"BTC": series(flat_candles(0, 60_000, 100.0))},
             s2, end_ms=60_000)
    assert r2.sim_copies == 1
    assert r2.sim_fees_usd == pytest.approx(HL_MIN_ORDER_USD * TAKER_FEE_RATE)


def test_unknown_max_leverage_skips_the_open():
    r = run([evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)], {}, fixed(), end_ms=60_000, max_lev=0)
    assert r.sim_copies == 0
    assert any(f.startswith("max_leverage_unknown:BTC") for f in r.flags)


def test_position_predating_window_is_invisible():
    r = run([evt("BTC", 0, "close", "long", 1.0, 1.0, 0.0, 100.0)], {"BTC": series(flat_candles(0, 60_000, 100.0))},
            fixed(), end_ms=60_000)
    assert r.sim_copies == 0 and r.sim_return_pct == 0.0


def test_add_moves_the_liquidation_price_with_the_average_entry():
    rows = flat_candles(0, 600_000, 100.0)
    for row in rows:
        if row["t"] >= 120_000:
            row["o"] = row["h"] = row["l"] = row["c"] = 110.0
    rows[6]["l"] = 107.0         # below the new liq (~107.9) but far above the old one (~99)
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0),
              evt("BTC", 150_000, "add", "long", 9.0, 1.0, 10.0, 110.0)]
    r = run(events, {"BTC": series(rows)}, fixed(HL_MIN_ORDER_USD, 50), equity=1000.0, end_ms=600_000)
    assert r.sim_liquidations == 1


def test_isolated_unrealized_gain_cannot_back_more_margin():
    """Regression (found tracing 0x30afce2f on xyz:DRAM): adds were checked
    against equity INCLUDING the copy's own unrealized gain, so its margin
    grew to $126 on a $100 account and one liquidation cost -127%."""
    rows = flat_candles(0, 600_000, 100.0)
    for row in rows:
        if row["t"] >= 120_000:
            row["o"] = row["h"] = row["l"] = row["c"] = 150.0     # big unrealized gain after our entry
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)]
    events += [evt("BTC", 120_000 + i * 1000, "add", "long", 1.0, 1.0 + i, 2.0 + i, 150.0) for i in range(60)]
    s = fixed(90.0, 1)        # $90 margin on open, $100 account: adds must find no room
    r = run(events, {"BTC": series(rows)}, s, equity=100.0, end_ms=600_000)
    assert any(f.startswith("margin_room:BTC") for f in r.flags)
    assert r.sim_return_pct > -100.0
