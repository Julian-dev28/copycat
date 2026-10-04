"""Live eval: hits the real Hyperliquid API. Not part of the gate (not
run on every commit) -- run explicitly with:

    .venv/bin/python -m pytest services/hl/tests/test_live.py -m live -v

Every assertion here is a smoke check on SHAPE (did we get a real, sane
value back), not a check on a specific number -- real balances/prices move.
"""
from __future__ import annotations

import time

import pytest
from hl.venue import HlVenue

pytestmark = pytest.mark.live

LEADER = "0xe2823659be02e0f48a4660e4da008b5e1abfdf29"


def test_live_account_state():
    v = HlVenue()
    state = v.account_state(LEADER)
    assert state is not None, "account_state returned None against the real API"
    assert state["equity_perp_usd"] >= 0
    assert isinstance(state["positions"], dict)
    assert isinstance(state["raw_positions"], dict)
    # userAbstraction is a bare JSON string; this wallet was "unifiedAccount" on 2026-10-04
    assert isinstance(state.get("abstraction"), str)
    if state["abstraction"] in ("unifiedAccount", "portfolioMargin"):
        assert len(set(state["available"].values())) == 1   # one spot pool for every dex
    print(f"\n[live] account_state({LEADER}): equity_perp_usd={state['equity_perp_usd']:.2f} "
          f"spot_usdc={state['spot_usdc']:.2f} abstraction={state['abstraction']} "
          f"available_main={state['available'].get('')} positions={list(state['positions'].keys())}")


def test_live_extras():
    v = HlVenue()
    extras = v.extras(LEADER)
    assert extras is not None, "extras returned None against the real API"
    assert extras["spot_other_usd"] >= 0
    assert extras["staked_hype_usd"] >= 0
    print(f"\n[live] extras({LEADER}): spot_other_usd={extras['spot_other_usd']:.2f} "
          f"staked_hype_usd={extras['staked_hype_usd']:.2f}")


def test_live_fills_last_1d():
    v = HlVenue()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 86_400_000
    fills = v.fills(LEADER, start_ms, end_ms)
    assert fills is not None, "fills returned None against the real API"
    for f in fills:
        assert start_ms <= f["time_ms"] <= end_ms
        assert f["side"] in ("B", "A")
    print(f"\n[live] fills({LEADER}, last 1d): {len(fills)} fills")


def test_live_fills_aggregate_by_time_matches_raw():
    """aggregate_by_time merges one order's partials at one ms. Checked against
    the raw fills of the same window: per (ms, coin, side) the sizes, closed
    PnL and fees sum the same, the first row's start_position is the raw
    group's first, and every coin's end position is unchanged. 2026-10-05:
    870 raw -> 189 aggregated over 30d (the 2 missing groups were spot dust)."""
    from collections import OrderedDict

    v = HlVenue()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 30 * 86_400_000
    raw = v.fills(LEADER, start_ms, end_ms)
    agg = v.fills(LEADER, start_ms, end_ms, aggregate_by_time=True)
    assert raw is not None and agg is not None
    assert len(agg) <= len(raw)

    def perp(rows):
        return [f for f in rows if not f["coin"].startswith("@")]

    def groups(rows):
        g = OrderedDict()
        for f in perp(rows):
            g.setdefault((f["time_ms"], f["coin"], f["side"]), []).append(f)
        return g

    def signed(f):
        return f["sz"] if f["side"] == "B" else -f["sz"]

    gr, ga = groups(raw), groups(agg)
    assert set(gr) == set(ga)
    merged = 0
    for k, rs in gr.items():
        a = ga[k]
        merged += len(a) < len(rs)
        assert sum(f["sz"] for f in a) == pytest.approx(sum(f["sz"] for f in rs), rel=1e-9, abs=1e-9)
        assert sum(f["closed_pnl"] for f in a) == pytest.approx(sum(f["closed_pnl"] for f in rs), abs=1e-4)
        assert sum(f["fee"] for f in a) == pytest.approx(sum(f["fee"] for f in rs), abs=1e-5)
        assert a[0]["start_position"] == pytest.approx(rs[0]["start_position"], abs=1e-9)
        vwap_raw = sum(f["px"] * f["sz"] for f in rs) / sum(f["sz"] for f in rs)
        vwap_agg = sum(f["px"] * f["sz"] for f in a) / sum(f["sz"] for f in a)
        assert vwap_agg == pytest.approx(vwap_raw, rel=1e-6)

    def end_positions(rows):
        last = {}
        for f in perp(rows):
            last[f["coin"]] = f["start_position"] + signed(f)
        return last

    er, ea = end_positions(raw), end_positions(agg)
    assert er.keys() == ea.keys()
    for c in er:
        assert ea[c] == pytest.approx(er[c], abs=1e-6), c
    print(f"\n[live] fills({LEADER}, 30d): raw={len(raw)} aggregated={len(agg)} "
          f"groups={len(gr)} merged_groups={merged}")


def test_live_leaderboard():
    v = HlVenue()
    rows = v.leaderboard()
    assert rows is not None, "leaderboard returned None against the real API"
    assert len(rows) > 100, "expected thousands of leaderboard rows"
    top5 = rows[:5]
    for r in top5:
        assert "ethAddress" in r
        assert "accountValue" in r
    print(f"\n[live] leaderboard: {len(rows)} rows. Top 5 account values: "
          f"{[r['accountValue'] for r in top5]}")


def test_live_mid_btc():
    v = HlVenue()
    px = v.mid("BTC")
    assert px > 1000, f"BTC mid looks wrong: {px}"
    print(f"\n[live] mid(BTC) = {px}")


def test_live_max_leverage_btc():
    v = HlVenue()
    lev = v.max_leverage("BTC")
    assert lev >= 3, f"BTC max_leverage looks wrong (never silently 1): {lev}"
    print(f"\n[live] max_leverage(BTC) = {lev}")


def test_live_portfolio():
    v = HlVenue()
    pf = v.portfolio(LEADER)
    assert pf is not None, "portfolio returned None against the real API"
    windows = dict(pf)
    for w in ("day", "week", "month", "allTime", "perpDay", "perpWeek", "perpMonth", "perpAllTime"):
        assert w in windows, f"missing window {w}"
        assert set(windows[w]) >= {"accountValueHistory", "pnlHistory", "vlm"}
    hist = windows["allTime"]["accountValueHistory"]
    assert hist and isinstance(hist[0][0], int) and isinstance(hist[0][1], str)
    print(f"\n[live] portfolio({LEADER}): windows={list(windows)} "
          f"allTime points={len(hist)} allTime vlm={windows['allTime']['vlm']}")


def test_live_open_orders():
    v = HlVenue()
    orders = v.open_orders(LEADER)
    assert orders is not None, "open_orders returned None against the real API"
    for o in orders:
        assert o["side"] in ("B", "A")
        assert float(o["sz"]) > 0
        assert isinstance(o["oid"], int)
    print(f"\n[live] open_orders({LEADER}): {len(orders)} orders "
          f"coins={sorted({o['coin'] for o in orders})}")


def test_live_leaderboard_parse_rows():
    from hl.leaderboard import parse_rows
    raw = HlVenue().leaderboard()
    assert raw is not None
    rows = parse_rows(raw)
    assert len(rows) >= 0.99 * len(raw), f"parse_rows dropped too many: {len(rows)}/{len(raw)}"
    assert isinstance(rows[0]["allTime"]["pnl"], float)
    print(f"\n[live] parse_rows: {len(rows)}/{len(raw)} rows parsed")


@pytest.mark.parametrize("coin", ["BTC", "xyz:TSLA"])
def test_live_market_stats(coin):
    s = HlVenue().market_stats(coin)
    assert s is not None, f"market_stats({coin}) returned None against the real API"
    assert s["mark_px"] > 0 and s["mid_px"] > 0
    assert abs(s["mid_px"] / s["mark_px"] - 1) < 0.05   # mid and mark agree to within 5%
    assert s["day_volume_usd"] > 0 and s["open_interest_usd"] > 0
    assert s["max_leverage"] >= 1
    print(f"\n[live] market_stats({coin}): {s}")


@pytest.mark.parametrize("coin", ["BTC", "xyz:TSLA"])
def test_live_depth_usd(coin):
    v = HlVenue()
    buy, sell = v.depth_usd(coin, True, 1.0), v.depth_usd(coin, False, 1.0)
    assert buy is not None and sell is not None, f"depth_usd({coin}) returned None"
    assert buy > 0 and sell > 0
    assert v.depth_usd(coin, True, 0.1) <= buy   # wider band never holds less
    print(f"\n[live] depth_usd({coin}, 1%): buy=${buy:,.0f} sell=${sell:,.0f}")
