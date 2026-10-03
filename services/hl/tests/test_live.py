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
    print(f"\n[live] account_state({LEADER}): equity_perp_usd={state['equity_perp_usd']:.2f} "
          f"spot_usdc={state['spot_usdc']:.2f} positions={list(state['positions'].keys())}")


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
