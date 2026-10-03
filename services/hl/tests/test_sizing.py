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


# ── HL price rule below $1: 5 sig figs from the first non-zero digit ────────

def test_round_price_sub_cent_keeps_five_sig_figs_up_to_tick():
    # 0.000123 at sz_decimals=0: tick allows 6 decimals, 5 sig figs allow 9 -> 6.
    # The old rule gave 5 decimals and a buy rounded to 0.00013 (+5.7%).
    assert sizing.round_price(0.000123, sz_decimals=0, is_buy=True) == "0.000123"
    assert sizing.round_price(0.000123, sz_decimals=0, is_buy=False) == "0.000123"


def test_round_price_sub_cent_direction():
    assert sizing.round_price(0.0001234567, sz_decimals=0, is_buy=True) == "0.000124"
    assert sizing.round_price(0.0001234567, sz_decimals=0, is_buy=False) == "0.000123"


def test_round_price_sub_cent_tick_limit_wins_over_sig_figs():
    # sz_decimals=2 -> only 4 decimals allowed
    assert sizing.round_price(0.000123, sz_decimals=2, is_buy=True) == "0.0002"
    assert sizing.round_price(0.000123, sz_decimals=2, is_buy=False) == "0.0001"


def test_round_price_one_cent_range():
    assert sizing.round_price(0.01234567, sz_decimals=0, is_buy=True) == "0.012346"
    assert sizing.round_price(0.01234567, sz_decimals=0, is_buy=False) == "0.012345"


def test_round_price_half_dollar():
    assert sizing.round_price(0.5, sz_decimals=0, is_buy=True) == "0.50000"
    assert sizing.round_price(0.5, sz_decimals=1, is_buy=False) == "0.50000"
    assert sizing.round_price(0.543216, sz_decimals=0, is_buy=True) == "0.54322"
    assert sizing.round_price(0.543216, sz_decimals=0, is_buy=False) == "0.54321"


def test_round_price_spot_allows_8_decimals():
    assert sizing.round_price(0.0001234567, sz_decimals=0, is_perp=False, is_buy=False) == "0.00012345"


def test_round_price_large_integer_always_allowed():
    assert sizing.round_price(123456.7, sz_decimals=5, is_buy=True) == "123457"


# ── reduce_only sizing is never bumped ──────────────────────────────────────

def test_order_size_reduce_only_not_bumped():
    assert sizing.order_size(0.05, 100.0, 2, reduce_only=True) == 0.05
    assert sizing.order_size(0.05, 100.0, 2, reduce_only=False) * 100.0 >= sizing.MIN_ORDER_USD


def test_size_for_notional_reduce_only_not_bumped(monkeypatch):
    monkeypatch.setattr(meta, "sz_decimals", lambda coin: 2)
    assert sizing.size_for_notional("BTC", 5.0, 100.0, reduce_only=True) == 0.05
