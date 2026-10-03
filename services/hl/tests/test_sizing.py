"""Gate tests for hl.sizing: pure price/size rounding math, no network."""
from __future__ import annotations

from hl import meta, sizing


def test_round_price_perp_tick_and_sigfig():
    # BTC-like: sz_decimals=5, price ~85002 -> 5 sig figs leaves 0 decimals;
    # is_buy=True rounds UP (more aggressive for a buy) -> 85003, not 85002.
    assert sizing.round_price(85002.345, sz_decimals=5, is_buy=True) == "85003"
    assert sizing.round_price(85002.345, sz_decimals=5, is_buy=False) == "85002"


def test_round_price_buy_rounds_up_sell_rounds_down():
    # price 0.123456, sz_decimals=0 -> tick decimals = 6, sigfig decimals = 5-0=5 -> min=5
    buy = sizing.round_price(0.123456, sz_decimals=0, is_buy=True)
    sell = sizing.round_price(0.123456, sz_decimals=0, is_buy=False)
    assert float(buy) >= 0.123456
    assert float(sell) <= 0.123456
    assert buy != sell


def test_round_price_none_direction_is_half_up():
    out = sizing.round_price(1.23455, sz_decimals=1, is_buy=None)
    assert out  # just must not raise; half-up is the non-order fallback


def test_round_price_non_positive_returns_zero_string():
    assert sizing.round_price(0.0, sz_decimals=5) == "0"
    assert sizing.round_price(-5.0, sz_decimals=5) == "0"


def test_min_order_size_covers_the_floor():
    price = 2.0
    sz_dec = 2
    sz = sizing.min_order_size(price, sz_dec)
    assert sz * price >= sizing.MIN_ORDER_USD
    # rounded UP to the size tick, not just precision-truncated
    tick = 10.0 ** (-sz_dec)
    assert round(sz / tick) == sz / tick


def test_min_order_size_integer_coin_overshoots_correctly():
    # sz_decimals=0 (integer-size coin): $10.50 / $0.084 ~= 125 coins, not 100
    sz = sizing.min_order_size(price=0.084, sz_decimals=0)
    assert sz == 125.0


def test_min_order_size_non_positive_price():
    assert sizing.min_order_size(0.0, 2) == 0.0


def test_size_for_notional_invalid_inputs_return_zero():
    assert sizing.size_for_notional("BTC", 0, 100.0) == 0.0
    assert sizing.size_for_notional("BTC", 100.0, 0.0) == 0.0
    assert sizing.size_for_notional("BTC", -5, 100.0) == 0.0


def test_size_for_notional_rounds_to_sz_decimals(monkeypatch):
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 3)
    size = sizing.size_for_notional("BTC", 100.0, 50.0)
    assert size == 2.0  # 100/50, already at 3dp precision


def test_size_for_notional_bumps_to_min_order_floor(monkeypatch):
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 2)
    # $1 notional at mid $100 -> 0.01 coin ($1), far under the $10.50 floor
    size = sizing.size_for_notional("BTC", 1.0, 100.0)
    assert size * 100.0 >= sizing.MIN_ORDER_USD
