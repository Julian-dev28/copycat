"""Copy-sim tests, run against the REAL engine.sizing (pure, no I/O, no
network -- safe for the gate lane) so these tests prove the sim actually
obeys the live engine's rules, not a reimplementation of them."""
from __future__ import annotations

import pytest
from engine import sizing as real_sizing

from contracts.models import HL_MIN_ORDER_USD, LeverageMode, MarginMode, Settings, SizingMode
from discovery.positions import PositionEvent
from discovery.sim import TAKER_FEE_RATE, simulate_wallet

from discovery_fakes import FakeVenue, flat_candles


def evt(coin, time_ms, kind, side, delta_sz, start, end, px):
    return PositionEvent(coin=coin, time_ms=time_ms, kind=kind, side=side, delta_sz=delta_sz,
                          start_position=start, end_position=end, px=px)


def test_open_add_reduce_close_mechanics_and_fee_accounting(conn):
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    venue.set_candles("BTC", "1m", flat_candles(0, 420_000, 100.0))

    settings = Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=20.0,
                         leverage_mode=LeverageMode.fixed, leverage=5, max_position_leverage=50,
                         margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0,
                         min_order_bump=True, max_open_copies=10)

    events = [
        evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0),
        evt("BTC", 120_000, "add", "long", 0.5, 1.0, 1.5, 102.0),
        evt("BTC", 240_000, "reduce", "long", 0.75, 1.5, 0.75, 98.0),
        evt("BTC", 360_000, "close", "long", 0.75, 0.75, 0.0, 101.0),
    ]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=420_000, sizing=real_sizing)

    assert result.sim_copies == 1
    assert result.sim_liquidations == 0
    assert result.sim_skipped_min_order == 0
    # open=20.0, add bumped 10.0->10.5, reduce=15.25 (half of 30.5), close=remaining 15.25
    expected_fees = TAKER_FEE_RATE * (20.0 + 10.5 + 15.25 + 15.25)
    assert result.sim_fees_usd == pytest.approx(expected_fees, rel=1e-6)
    # flat price the whole way: the only P&L is fees + the bid/ask slippage on each round trip
    assert -0.1 < result.sim_return_pct < 0
    assert -0.1 < result.sim_max_drawdown_pct <= 0


def test_sub_bump_floor_notional_is_skipped(conn):
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    venue.set_candles("BTC", "1m", flat_candles(0, 60_000, 100.0))

    settings = Settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=0.10,
                         leverage_mode=LeverageMode.fixed, leverage=10, max_position_leverage=50,
                         margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0, min_order_bump=True)
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=60_000, sizing=real_sizing)

    assert result.sim_copies == 0
    assert result.sim_skipped_min_order == 1
    assert result.sim_fees_usd == 0.0


def test_notional_above_bump_floor_gets_rounded_up_to_exchange_minimum(conn):
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    venue.set_candles("BTC", "1m", flat_candles(0, 60_000, 100.0))

    # 0.30 * 10x leverage = $3.00 raw -- below the $10.50 floor but >= the 25% bump threshold ($2.625)
    settings = Settings(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=0.30,
                         leverage_mode=LeverageMode.fixed, leverage=10, max_position_leverage=50,
                         margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0, min_order_bump=True)
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=60_000, sizing=real_sizing)

    assert result.sim_copies == 1
    assert result.sim_skipped_min_order == 0
    assert result.sim_fees_usd == pytest.approx(HL_MIN_ORDER_USD * TAKER_FEE_RATE, rel=1e-6)


def test_liquidation_triggers_on_adverse_candle_wick(conn):
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    candles = flat_candles(0, 300_000, 100.0)
    for row in candles:
        if row["t"] == 180_000:
            row["l"] = 98.0   # wick below the ~99.02 isolated liq price at 50x
    venue.set_candles("BTC", "1m", candles)

    settings = Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=HL_MIN_ORDER_USD,
                         leverage_mode=LeverageMode.fixed, leverage=50, max_position_leverage=50,
                         margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0, min_order_bump=True)
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=100.0,
                              window_start_ms=0, window_end_ms=300_000, sizing=real_sizing)

    assert result.sim_copies == 1
    assert result.sim_liquidations == 1
    assert any(f.startswith("liquidated:BTC") for f in result.flags)
    margin = HL_MIN_ORDER_USD / 50
    fee = HL_MIN_ORDER_USD * TAKER_FEE_RATE
    expected_final = 100.0 - margin - fee
    expected_return = (expected_final / 100.0 - 1.0) * 100.0
    assert result.sim_return_pct == pytest.approx(expected_return, rel=1e-6)


def test_drawdown_reflects_intratrade_price_dip_not_just_close_pnl(conn):
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    candles = flat_candles(0, 300_000, 100.0)
    for row in candles:
        if 120_000 <= row["t"] <= 180_000:
            row["o"] = row["h"] = row["l"] = row["c"] = 90.0   # dip
    venue.set_candles("BTC", "1m", candles)

    settings = Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=50.0,
                         leverage_mode=LeverageMode.fixed, leverage=5, max_position_leverage=50,
                         margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0, min_order_bump=True)
    events = [
        evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0),
        evt("BTC", 240_000, "close", "long", 1.0, 1.0, 0.0, 100.0),
    ]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=300_000, sizing=real_sizing)

    assert result.sim_liquidations == 0
    assert result.sim_max_drawdown_pct < -0.3   # the dip shows up even though price recovered before close
    assert result.sim_return_pct > -0.3          # but the close happens back near the original price


def test_unknown_max_leverage_skips_the_open_rather_than_guessing_1x(conn):
    """max_leverage() == 0 means unknown (contracts/venue.py). The sim must
    never silently size a position at a fabricated 1x leverage when it
    can't determine the real cap."""
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 0)
    venue.set_candles("BTC", "1m", flat_candles(0, 60_000, 100.0))

    settings = Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=20.0,
                         leverage_mode=LeverageMode.fixed, leverage=5, max_position_leverage=50)
    events = [evt("BTC", 0, "open", "long", 1.0, 0.0, 1.0, 100.0)]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=60_000, sizing=real_sizing)

    assert result.sim_copies == 0
    assert any(f.startswith("max_leverage_unknown:BTC") for f in result.flags)


def test_no_position_predating_window_is_invisible_to_sim(conn):
    """An 'add'/'reduce'/'close' for a coin with no prior in-window open is a
    position that existed before our fetch window started -- we never saw
    the open, so we have nothing to add to / reduce / close. Documented
    bias: only opens inside the window get copied."""
    venue = FakeVenue()
    venue.set_max_leverage("BTC", 50)
    venue.set_candles("BTC", "1m", flat_candles(0, 60_000, 100.0))

    settings = Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=20.0,
                         leverage_mode=LeverageMode.fixed, leverage=5, max_position_leverage=50)
    events = [evt("BTC", 0, "close", "long", 1.0, 1.0, 0.0, 100.0)]

    result = simulate_wallet(conn, venue, events, leader_equity_usd=1_000_000.0,
                              leader_leverage_by_coin={}, settings=settings, sim_equity_usd=1000.0,
                              window_start_ms=0, window_end_ms=60_000, sizing=real_sizing)

    assert result.sim_copies == 0
    assert result.sim_return_pct == 0.0
