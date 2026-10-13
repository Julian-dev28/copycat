"""Scout metric formulas (spec section 2) on hand-computed fixtures."""
from __future__ import annotations

import pytest
from discovery.scout import metrics as M
from test_scout_helpers import DAY, HOUR, NOW, fill, portfolio

from contracts.models import PnlWindow, TradingStyle

R7 = [0.01, -0.02, 0.03, 0.0, 0.01, -0.01, 0.02]   # mean 0.04/7


def test_drawdown_spec_example():
    # I = 1.1, 0.88, 0.924 -> worst 0.88 / 1.1 - 1 = -20%
    assert M.max_drawdown_pct([0.10, -0.20, 0.05]) == pytest.approx(20.0)
    assert M.max_drawdown_pct([0.01, 0.02]) == 0.0
    assert M.max_drawdown_pct([]) is None


def test_sharpe_sortino_hand_computed():
    # mean 0.0057142857, stdev(ddof=1) 0.0171824939 -> 0.33256 * sqrt(365) = 6.35363
    assert M.sharpe(R7) == pytest.approx(6.353634, abs=1e-5)
    # downside dev sqrt((0.0004 + 0.0001) / 7) = 0.0084515 -> 12.91732
    assert M.sortino(R7) == pytest.approx(12.917319, abs=1e-5)


def test_ratios_null_below_7_days_and_zero_stdev():
    assert M.sharpe(R7[:6]) is None
    assert M.sortino(R7[:6]) is None
    assert M.sharpe([0.01] * 7) is None
    assert M.sortino([0.01, 0.02] * 4) is None          # no negative day


def test_sharpe_annualised_by_mean_gap_for_sparse_series():
    assert M.sharpe(R7, [3.0] * 7) == pytest.approx(6.353634 / 3 ** 0.5, abs=1e-5)


def test_daily_returns_resample_and_av_floor():
    d0 = (NOW // DAY) * DAY - 3 * DAY
    pnl = [(d0 + HOUR, 0.0), (d0 + 5 * HOUR, 999.0), (d0 + DAY + HOUR, 1000.0),
           (d0 + 2 * DAY + HOUR, -1000.0), (d0 + 3 * DAY + HOUR, -990.0)]
    av = [(d0 + HOUR, 10_000.0), (d0 + DAY + HOUR, 11_000.0), (d0 + 2 * DAY + HOUR, 50.0),
          (d0 + 3 * DAY + HOUR, 60.0)]
    dr = M.daily_returns(pnl, av)
    # day0 close is the LAST point of day 0 (999); day 3 skipped: prior AV 50 < 100.
    # day 1: AV +1000 but PnL +1, so $999 was deposited and is at risk: 1 / (10_000 + 999)
    assert dr.returns == pytest.approx([1 / 10_999, -2000 / 11_000])
    assert dr.days == [d0 + DAY, d0 + 2 * DAY]


def test_profitable_days_and_streak():
    assert M.profitable_days_pct(R7) == pytest.approx(4 / 7 * 100)
    raw = portfolio([0, 5, 6, -1, 2, 3, 4, 0, 1], now=NOW)
    cal = M.daily_pnl(M.parse_portfolio(raw), NOW)
    assert [p.value for p in cal] == [5, 6, -1, 2, 3, 4, 0, 1]
    assert M.longest_win_streak_days(cal) == 3


def test_risk_stats_from_portfolio_month():
    raw = portfolio([0] + [100.0, -50.0] * 15, av=10_000.0)
    port = M.parse_portfolio(raw)
    rs = M.risk_stats(PnlWindow.month, port["month"]["pnl"], port["month"]["av"])
    assert rs.days == 30 and rs.profitable_days_pct == 50.0
    assert rs.max_drawdown_pct == pytest.approx(50 / 10_100 * 100, abs=1e-3)


def _t(h):
    return NOW - 10 * DAY + h * HOUR


def test_round_trips_flip_partials_edge_and_fees():
    fills = [
        fill(_t(0), "ETH", 10.0, 5.0, "A", 5.0, pnl=3.0, fee=0.1),     # closes a trip opened before the window
        fill(_t(1), "BTC", 100.0, 2.0, "B", 0.0, fee=0.2),             # open long 2
        fill(_t(2), "BTC", 110.0, 2.0, "B", 2.0, fee=0.2),             # add -> 4, entry avg 105
        fill(_t(3), "BTC", 120.0, 1.0, "A", 4.0, pnl=15.0, fee=0.1),   # partial reduce
        fill(_t(5), "BTC", 90.0, 7.0, "A", 3.0, pnl=-45.0, fee=0.3),   # flip: close 3 long, open 4 short
        fill(_t(9), "BTC", 80.0, 4.0, "B", -4.0, pnl=40.0, fee=0.2),   # close the short
        fill(_t(10), "SOL", 1.0, 1.0, "B", 0.0),                        # still open: dropped
        fill(_t(11), "@151", 1.0, 1.0, "B", 0.0),                       # spot: ignored
    ]
    tr = M.round_trips(fills)
    assert [(t.coin, t.side) for t in tr] == [("BTC", "long"), ("BTC", "short")]
    long_, short = tr
    assert long_.entry_px == pytest.approx(105.0)
    assert long_.exit_px == pytest.approx((120 * 1 + 90 * 3) / 4)
    assert long_.net_pnl_usd == pytest.approx(15 - 45 - (0.2 + 0.2 + 0.1 + 0.3))
    assert not long_.win and long_.hold_h == 4.0
    assert short.net_pnl_usd == pytest.approx(40 - 0.2) and short.win
    st = M.trade_stats(PnlWindow.month, tr, fills, NOW)
    assert (st.trips, st.wins, st.long_trips, st.short_trips) == (2, 1, 1, 1)
    assert st.win_rate_pct == 50.0 and st.median_hold_h == pytest.approx(4.0)
    assert M.trade_stats(PnlWindow.week, tr, fills, NOW).trips == 0       # opened 10 d ago


@pytest.mark.parametrize("opd,hold,trips,want", [
    (100.1, None, 0, TradingStyle.algo), (100.0, 0.1, 5, TradingStyle.scalp),
    (1, 0.25, 3, TradingStyle.intraday), (1, 23.99, 3, TradingStyle.intraday),
    (1, 24.0, 3, TradingStyle.swing), (1, 167.9, 3, TradingStyle.swing),
    (1, 168.0, 3, TradingStyle.position), (1, 1.0, 2, None)])
def test_style_boundaries(opd, hold, trips, want):
    assert M.classify_style(opd, hold, trips) == want


def test_coin_stats_hip3_and_truncation():
    fills = [fill(1, "BTC", 100.0, 1.0, "B", 0.0, fee=1.0), fill(2, "xyz:TSLA", 300.0, 1.0, "B", 0.0),
             fill(3, "BTC", 100.0, 1.0, "A", 1.0, pnl=10.0, fee=1.0)]
    cs = M.coin_stats(fills, [])
    assert [(c.coin, c.volume_usd, c.pnl_usd) for c in cs] == [("xyz:TSLA", 300.0, 0.0), ("BTC", 200.0, 8.0)]
    assert M.hip3_share(cs) == pytest.approx(0.6)
    many = [fill(NOW - DAY + i, "BTC", 1, 1, "B", 0) for i in range(9_000)]
    assert M.fills_truncated(many, NOW - 30 * DAY) and not M.fills_truncated(many[:10], NOW - 30 * DAY)


def test_account_risk_and_positions():
    raw = {"BTC": {"szi": "2", "entryPx": "100", "positionValue": "220", "unrealizedPnl": "20",
                   "returnOnEquity": "0.5", "leverage": {"type": "cross", "value": 5}, "liquidationPx": "88",
                   "marginUsed": "44", "cumFunding": {"sinceOpen": "1.5"}},
           "ETH": {"szi": "-1", "entryPx": "50", "positionValue": "60", "unrealizedPnl": "-10",
                   "returnOnEquity": "-0.2", "leverage": {"type": "isolated", "value": 3}, "liquidationPx": None,
                   "marginUsed": "20", "cumFunding": {"sinceOpen": "0"}}}
    views = M.position_views(raw)
    btc = views[0]
    assert btc.mark_px == 110 and btc.liq_distance_pct == pytest.approx(20.0) and btc.roe_pct == 50.0
    acct = M.account_risk({"equity_perp_usd": 1000.0, "spot_usdc": 5.0}, {"spot_other_usd": 1.0,
                                                                          "staked_hype_usd": 7.0}, views)
    assert acct.account_leverage == pytest.approx(0.28) and acct.margin_usage_pct == pytest.approx(6.4)
    assert acct.nearest_liq_pct == pytest.approx(20.0) and acct.long_bias_pct == pytest.approx(220 / 280 * 100)
    assert (acct.spot_usd, acct.staked_usd, acct.unrealized_pnl_usd) == (6.0, 7.0, 10.0)
    assert M.bias_label(acct.long_bias_pct) == "long"


def test_tiers():
    assert [M.size_tier(v).value for v in (9_999, 10_000, 100_000, 1e6, 1e7)] == ["S", "M", "L", "XL", "XXL"]


def test_real_liquidations_distinct_from_ordinary_closes():
    """user_consensus P0 #3: the wallet's OWN real liquidations (HL `dir`
    "Liquidated ..."), not the copy-sim's. An ordinary close is never
    counted; only fills whose dir actually starts with "Liquidated" are."""
    fills = [
        dict(fill(NOW - 3 * DAY, "BTC", 100.0, 1.0, "B", 0.0), dir="Open Long"),
        dict(fill(NOW - 2 * DAY, "BTC", 90.0, 1.0, "A", 1.0), dir="Close Long"),       # ordinary close, not a liq
        dict(fill(NOW - DAY, "ETH", 50.0, 2.0, "A", 2.0), dir="Liquidated Isolated Long"),
    ]
    assert M.real_liquidations(fills) == (1, NOW - DAY)
    assert M.real_liquidations([dict(f, dir="Close Long") for f in fills[:1]]) == (0, None)
    assert M.real_liquidations([]) == (0, None)
    assert [M.pnl_tier(v).value for v in (-1, 0, 1e5, 1e6)] == ["losing", "up", "strong", "elite"]
