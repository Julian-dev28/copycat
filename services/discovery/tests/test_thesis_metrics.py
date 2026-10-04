"""Fingerprint metrics on a hand-built 5-trip book (no candles): adds and
scale-outs, payoff, loser-hold ratio, hour/weekday histograms, p90,
session window, leverage vs equity, concentration, tags at their edges,
example selection and caveats."""
from __future__ import annotations

import pytest
from discovery.thesis import config as C
from discovery.thesis.fingerprint import (
    assign_tags,
    best_session,
    build_fingerprint,
    equity_at,
    p90,
    top_profit_coin,
)
from discovery.thesis.trips import build_trips
from test_thesis_fixtures import ADDR, T0, D, H, fill, trip_fills

NOW = T0 + 10 * D


def book():
    f = []
    f += trip_fills("BTC", "long", T0 + H, 100, T0 + 11 * H, 110)                           # +10, 10h
    f += trip_fills("BTC", "long", T0 + D + H, 100, T0 + D + 3 * H, 95)                     # -5, 2h
    f += trip_fills("ETH", "short", T0 + 2 * D + H, 50, T0 + 2 * D + 21 * H, 40, sz=2)      # +20, 20h
    f += trip_fills("ETH", "long", T0 + 3 * D + H, 50, T0 + 3 * D + 5 * H, 48, sz=2)        # -4, 4h
    o = T0 + 4 * D + H
    f += trip_fills("BTC", "long", o, 100, o + 6 * H, 110,
                    adds=[(o + 120_000, 1.0, 101), (o + 150_000, 0.5, 101)],                # 2 fills, 1 add
                    partial_exits=[(o + 5 * H, 1.0, 108)])                                  # +21.5, 6h
    return f


def fp_of(fills, equity=((T0, 1000.0),), now=NOW, days=30):
    return build_fingerprint(ADDR, fills, {}, list(equity), days, now)


def test_trips_count_adds_and_exits_as_actions():
    trips, still_open = build_trips(book())
    assert still_open == 0 and len(trips) == 5
    e = trips[-1]
    assert e.adds == 1 and e.exits == 2                      # the 30s-apart add fills merge into one action
    assert e.net_pnl_usd == pytest.approx(21.5)
    assert [t.adds for t in trips[:4]] == [0, 0, 0, 0]


def test_outcome_metrics():
    fp = fp_of(book())
    assert fp.trips_analyzed == 5
    assert fp.win_rate_pct == 60.0 and fp.long_pct == 80.0
    assert fp.avg_win_usd == pytest.approx((10 + 20 + 21.5) / 3, abs=0.01)
    assert fp.avg_loss_usd == -4.5
    assert fp.payoff_ratio == pytest.approx(((10 + 20 + 21.5) / 3) / 4.5, abs=0.001)
    assert fp.loser_hold_vs_winner == pytest.approx(3 / 10)  # median loser 3h / median winner 10h
    assert fp.median_hold_h == 6.0 and fp.p90_hold_h == 20.0
    assert fp.scales_in_pct == 20.0 and fp.scales_out_pct == 20.0 and fp.avg_adds_per_trip == 0.2


def test_timing_histograms():
    fp = fp_of(book())
    assert fp.hour_hist_utc[1] == 5 and sum(fp.hour_hist_utc) == 5 and len(fp.hour_hist_utc) == 24
    assert fp.weekday_hist == [1, 1, 1, 1, 1, 0, 0]


def test_leverage_and_worst_trip_vs_equity():
    fp = fp_of(book())
    assert fp.worst_trip_pct_of_equity == -0.5               # -5 on a 1000 account
    assert fp.max_leverage == pytest.approx(0.27, abs=0.01)  # trip E peaks at 2.5 x 108 = 270 notional
    no_eq = fp_of(book(), equity=())
    assert no_eq.avg_leverage is None and no_eq.worst_trip_pct_of_equity is None


def test_concentration_and_top_coins():
    fp = fp_of(book())
    assert fp.pnl_from_top_coin_pct == pytest.approx(26.5 / 42.5 * 100, abs=0.01)
    assert top_profit_coin(fp.top_coins)[0] == "BTC"
    assert {c.coin for c in fp.top_coins} == {"BTC", "ETH"}


def test_tags_on_the_book():
    assert fp_of(book()).tags == ["runs winners", "cuts losers fast", "concentrated", "session trader",
                                  "long biased"]


def test_helpers():
    assert p90([]) is None and p90([5.0]) == 5.0 and p90(list(range(1, 11))) == 9
    hist = [0] * 24
    hist[22], hist[23], hist[0], hist[1] = 2, 2, 2, 2
    hist[12] = 4
    assert best_session(hist) == (20, pytest.approx(66.67))  # wraps midnight, earliest start wins ties
    assert best_session([0] * 24) == (0, None)
    pts = [(100, 0.0), (200, 50.0), (300, 70.0)]
    assert equity_at(pts, 250) == 50.0 and equity_at(pts, 50) == 50.0 and equity_at([], 1) is None


@pytest.mark.parametrize("key,at,below,tag", [
    ("trend_aligned_pct", 65.0, 64.99, "trend follower"),
    ("pullback_pct", 40.0, 39.99, "dip buyer"),
    ("breakout_pct", 40.0, 39.99, "breakout buyer"),
    ("scales_in_pct", 50.0, 49.99, "scales in"),
    ("scales_out_pct", 50.0, 49.99, "scales out"),
    ("payoff_ratio", 2.0, 1.999, "runs winners"),
    ("win_rate_pct", 65.0, 64.99, "high win rate"),
    ("avg_leverage", 10.0, 9.99, "high leverage"),
    ("pnl_from_top_coin_pct", 60.0, 59.99, "concentrated"),
    ("session_pct", 50.0, 49.99, "session trader"),
    ("long_pct", 75.0, 74.99, "long biased"),
])
def test_tag_threshold_edges_ge(key, at, below, tag):
    assert tag in assign_tags({key: at}, 10, 10)
    assert tag not in assign_tags({key: below}, 10, 10)


def test_tag_threshold_edges_other_ops():
    assert "cuts losers fast" in assign_tags({"loser_hold_vs_winner": 0.4999}, 10, 10)
    assert "cuts losers fast" not in assign_tags({"loser_hold_vs_winner": 0.5}, 10, 10)
    assert "holds losers" in assign_tags({"loser_hold_vs_winner": 2.0}, 10, 10)
    assert "counter-trend" in assign_tags({"trend_aligned_pct": 35.0}, 10, 10)
    assert "counter-trend" not in assign_tags({"trend_aligned_pct": 35.01}, 10, 10)
    assert "short biased" in assign_tags({"long_pct": 25.0}, 10, 10)


def test_tag_sample_floors():
    m = {"trend_aligned_pct": 90.0, "payoff_ratio": 3.0}
    assert assign_tags(m, C.MIN_TRIPS_FOR_TAGS - 1, 10) == []
    assert assign_tags(m, 10, C.MIN_CONTEXT_FOR_ENTRY_TAGS - 1) == ["runs winners"]
    assert assign_tags({"payoff_ratio": None}, 10, 10) == []


def test_example_selection_rules():
    ex = fp_of(book()).examples
    whys = [e.why_shown for e in ex]
    assert whys[0] == "largest win" and ex[0].net_pnl_usd == 21.5 and ex[0].adds == 1
    assert whys[1] == "largest loss" and ex[1].net_pnl_usd == -5.0
    assert whys[2] == "typical winner (runs winners)" and ex[2].net_pnl_usd > 0
    assert whys[3] == "typical loser, cut early (cuts losers fast)" and ex[3].net_pnl_usd == -4.0
    assert whys[4] == "typical in-session entry (session trader)"
    assert len({(e.opened_ms, e.coin) for e in ex}) == len(ex)   # no trip shown twice


def test_examples_capped_at_8_and_unique():
    f = []
    for i in range(30):
        o = T0 + i * 6 * H
        f += trip_fills("SOL", "long" if i % 3 else "short", o, 100, o + 2 * H, 100 + (i % 7) - 3,
                        adds=[(o + H, 1.0, 100)] if i % 2 else ())
    ex = fp_of(f).examples
    assert len(ex) == C.MAX_EXAMPLES
    assert len({e.opened_ms for e in ex}) == C.MAX_EXAMPLES


def test_caveats():
    cv = fp_of(book()).caveats
    assert any("Only 5 closed trips" in c for c in cv)
    assert any("No usable 1h candles for 5 of 5 trips (BTC, ETH)" in c for c in cv)
    assert any("effective leverage" in c for c in cv)
    assert any("No closed round trips" in c for c in fp_of([]).caveats)
    few = fp_of(book()[:6])                                  # first 3 trips (2 fills each)
    assert few.tags == [] and any("too few to tag" in c for c in few.caveats)
    still = fp_of(book() + [fill(T0 + 5 * D, "SOL", "B", 1, 10, 0.0)])
    assert any("1 position opened in the window is still open" in c for c in still.caveats)
    assert any("Account value history unavailable" in c for c in fp_of(book(), equity=()).caveats)
