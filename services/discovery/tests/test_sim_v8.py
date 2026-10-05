"""Contract v8 in the copy-sim: trade_direction counter and the coin filters,
so the wallet projection and the what-if replay what the engine would do."""
from __future__ import annotations

import pytest
from discovery.candles_cache import Series
from discovery.positions import PositionEvent
from discovery.sim import SLIPPAGE_BPS, TAKER_FEE_RATE, simulate_wallet
from engine import sizing as real_sizing

from contracts.models import LeverageMode, MarginMode, Settings, SizingMode

M = 60_000
S = SLIPPAGE_BPS / 1e4


def evt(coin, t, kind, side, delta, start, end, px):
    return PositionEvent(coin=coin, time_ms=t, kind=kind, side=side, delta_sz=delta,
                         start_position=start, end_position=end, px=px)


def bars(prices, highs=None, lows=None):
    """One 1m bar per minute from t=0; o=c=price, h/l default to price."""
    s = Series()
    for i, p in enumerate(prices):
        h = (highs or {}).get(i, p)
        lo = (lows or {}).get(i, p)
        s.append(i * M, M, p, max(h, p), min(lo, p), p)
    return s


def fixed(direction="copy", **kw):
    return Settings(sizing_mode=SizingMode.fixed_notional, fixed_notional_usd=20.0,
                    leverage_mode=LeverageMode.fixed, leverage=5, max_position_leverage=50,
                    margin_mode=MarginMode.isolated, max_worse_entry_pct=50.0, min_order_bump=True,
                    trade_direction=direction, **kw)


def run(events, ser, settings, end_ms=9 * M, trace=None):
    coins = {e.coin for e in events}
    return simulate_wallet(events=events, series=ser, coin_max_lev={c: 50 for c in coins},
                           leader_equity_usd=1_000_000.0, leader_leverage_by_coin={}, settings=settings,
                           sim_equity_usd=1000.0, window_end_ms=end_ms, sizing=real_sizing, trace=trace)


# He opens long at 100 and closes at 110. Our fills are the next 1m bar's open
# +/- 2 bps against us: the open bar (t=1m) opens at 100, the close bar (t=7m) at 110.
WIN = [evt("BTC", 10_000, "open", "long", 1.0, 0.0, 1.0, 100.0),
       evt("BTC", 6 * M + 10_000, "close", "long", 1.0, 1.0, 0.0, 110.0)]
PRICES = [100.0] * 7 + [110.0] * 3


def test_a_winning_copy_is_a_losing_counter_minus_fees():
    lines_c, lines_k = [], []
    copy = run(WIN, {"BTC": bars(PRICES)}, fixed("copy"), trace=lines_c.append)
    counter = run(WIN, {"BTC": bars(PRICES)}, fixed("counter"), trace=lines_k.append)
    fees = TAKER_FEE_RATE * 40.0                         # $20 in, $20 out
    # copy: buy 100 x (1 + s), sell 110 x (1 - s)
    copy_pnl = 20.0 * (110.0 * (1 - S) / (100.0 * (1 + S)) - 1.0) - fees
    # counter: SELL 100 x (1 - s), BUY back 110 x (1 + s), short PnL
    counter_pnl = -20.0 * (110.0 * (1 + S) / (100.0 * (1 - S)) - 1.0) - fees
    assert copy.sim_return_pct == pytest.approx(copy_pnl / 1000.0 * 100.0, rel=1e-9)
    assert counter.sim_return_pct == pytest.approx(counter_pnl / 1000.0 * 100.0, rel=1e-9)
    assert copy.sim_return_pct > 0 > counter.sim_return_pct
    # the two legs cancel except for what both pay: fees and slippage
    assert copy_pnl + counter_pnl < -2 * fees
    assert copy.sim_fees_usd == pytest.approx(fees) == counter.sim_fees_usd
    assert "OPEN  BTC short" in lines_k[0] and "OPEN  BTC long" in lines_c[0]


def test_counter_is_liquidated_on_the_inverted_side():
    # lev 5, maint 1/(2 x 50): liq distance (0.2 - 0.01) = 19%.
    # A wick to 125 liquidates a counter SHORT (liq 99.98 x 1.19 = 118.98), never the copy long.
    ser = {"BTC": bars([100.0] * 9, highs={3: 125.0})}
    ev = WIN[:1]
    assert run(ev, ser, fixed("counter")).sim_liquidations == 1
    assert run(ev, ser, fixed("copy")).sim_liquidations == 0
    # and a wick to 75 liquidates the copy long, not the counter
    ser = {"BTC": bars([100.0] * 9, lows={3: 75.0})}
    assert run(ev, ser, fixed("copy")).sim_liquidations == 1
    assert run(ev, ser, fixed("counter")).sim_liquidations == 0


def test_counter_loss_on_liquidation_is_exactly_the_margin():
    ser = {"BTC": bars([100.0] * 9, highs={3: 125.0})}
    r = run(WIN[:1], ser, fixed("counter"))
    # margin $4 ($20 at 5x) + the $0.009 open fee
    assert r.sim_return_pct == pytest.approx(-(4.0 + TAKER_FEE_RATE * 20.0) / 1000.0 * 100.0)


def test_counter_add_and_reduce_stay_on_our_side():
    events = [evt("BTC", 10_000, "open", "short", 1.0, 0.0, -1.0, 100.0),   # he shorts: we go long
              evt("BTC", M + 10_000, "add", "short", 1.0, -1.0, -2.0, 100.0),
              evt("BTC", 2 * M + 10_000, "reduce", "short", 1.0, -2.0, -1.0, 100.0)]
    lines = []
    r = run(events, {"BTC": bars([100.0] * 9)}, fixed("counter"), trace=lines.append)
    assert "OPEN  BTC long" in lines[0]
    assert r.sim_copies == 1 and r.open_copies_at_end == 1 and r.sim_liquidations == 0


def test_counter_worse_entry_checks_our_side():
    # he is long @100; our counter short fills ~80, 20% under his entry: blocked at 10%
    ev = [evt("BTC", 10_000, "open", "long", 1.0, 0.0, 1.0, 100.0)]
    s = fixed("counter").model_copy(update={"max_worse_entry_pct": 10.0})
    r = run(ev, {"BTC": bars([80.0] * 9)}, s)
    assert r.sim_copies == 0 and "worse_entry:BTC" in r.flags
    # the same fill for a counter of his SHORT (we buy cheap) is fine
    ev = [evt("BTC", 10_000, "open", "short", 1.0, 0.0, -1.0, 100.0)]
    assert run(ev, {"BTC": bars([80.0] * 9)}, s).sim_copies == 1


def test_coin_filters_skip_opens_and_never_flag_exits():
    events = [evt("BTC", 10_000, "open", "long", 1.0, 0.0, 1.0, 100.0),
              evt("ETH", 10_000, "open", "long", 1.0, 0.0, 1.0, 100.0),
              evt("BTC", 3 * M, "close", "long", 1.0, 1.0, 0.0, 100.0)]
    ser = {"BTC": bars([100.0] * 9), "ETH": bars([100.0] * 9)}
    r = run(events, ser, fixed(coin_allowlist=["eth"]))
    assert r.sim_copies == 1 and r.flags.count("filtered:BTC") == 1
    r = run(events, ser, fixed(coin_blocklist=["ETH"]))
    assert r.sim_copies == 1 and "filtered:ETH" in r.flags and "filtered:BTC" not in r.flags
