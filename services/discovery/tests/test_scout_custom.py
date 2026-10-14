"""Custom wallets (contract v15): any address added by hand is scored and simmed
like the top 300, ranks on the board with `custom=True`, survives the stage-A
universe swap, leaves at once when removed, and is built even while a full
refresh is running (the refresh serves the request queue between its own
wallets instead of making it wait up to 45 minutes)."""
from __future__ import annotations

import pytest
from discovery.scout import public, store
from discovery.scout import refresh as R
from test_scout_helpers import addr, flat_15m, portfolio, trips
from test_scout_world import DAY, EQUITY, NOW, A, F, q, settings, world

X = addr(77)          # never on the leaderboard


@pytest.fixture
def w(tmp_path, monkeypatch):
    return world(tmp_path, monkeypatch)


def _give_history(v, a: str, coin: str = "SOL") -> None:
    first = NOW - 5 * DAY - 7 * DAY
    v.set_fills(a, trips(coin, 8, first, pnl=40.0, move=0.01))
    v.set_portfolio(a, portfolio([0] + [30.0, -5.0, 20.0] * 13, av=15_000.0))
    v.set_account_state(a, {"equity_perp_usd": 15_000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})
    v.set_candles(coin, "15m", flat_15m(100.5, NOW - 26 * DAY, NOW))


def _row(address: str):
    page = public.scout_page(q(limit=200))
    return next((r for r in page.rows if r.address == address), None)


def test_add_queues_then_the_tick_builds_and_ranks_it(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    _give_history(v, X)
    assert public.scout_custom_add("nope") is None
    cw = public.scout_custom_add(X)
    assert cw is not None and cw.address == X and cw.queued and not cw.on_board
    assert _row(X) is None
    R.tick(v, settings(), EQUITY, db_path=db)             # serves the request, republishes
    row = _row(X)
    assert row is not None and row.custom is True
    assert row.account_value_usd == 15_000.0               # from its own portfolio, no leaderboard row
    assert row.score.sim_copies > 0                        # simmed at the board's equity like everyone
    assert store.universe_row(conn, X)["source"] == "custom"
    assert public.scout_presets().custom == 1
    assert [r.address for r in public.scout_page(q(preset="custom")).rows] == [X]
    listed = public.scout_custom_list()
    assert [c.address for c in listed] == [X] and listed[0].on_board and not listed[0].queued


def test_leaderboard_filtered_wallet_becomes_custom_and_survives_the_swap(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    _give_history(v, F)                                    # F is on the leaderboard but under $10k: filtered
    assert store.universe_row(conn, F) is None
    public.scout_custom_add(F)
    R.tick(v, settings(), EQUITY, db_path=db)
    assert _row(F) is not None and _row(F).custom
    # a full ABC refresh swaps the universe; the custom row must survive it and keep ranking
    store.meta_set(conn, {"last_a_ms": 0, "last_b_ms": 0})
    R.tick(v, settings(), EQUITY, db_path=db)
    u = store.universe_row(conn, F)
    assert u is not None and u["source"] == "custom"
    assert _row(F) is not None and _row(F).custom
    assert public.scout_presets().custom == 1


def test_top_wallet_added_as_custom_keeps_its_leaderboard_row(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    cw = public.scout_custom_add(A)
    assert cw is not None and cw.on_board and not cw.queued   # already served: nothing to build
    R.tick(v, settings(), EQUITY, db_path=db)
    assert store.universe_row(conn, A)["source"] == "lb"
    # the mark shows after the next publish
    store.meta_set(conn, {"last_a_ms": 0, "last_b_ms": 0})
    R.tick(v, settings(), EQUITY, db_path=db)
    assert _row(A).custom is True
    assert public.scout_custom_remove(A) is True
    assert _row(A) is not None and _row(A).custom is False     # still ranked, mark gone at once
    assert store.universe_row(conn, A)["source"] == "lb"
    assert public.scout_custom_remove(A) is False


def test_remove_takes_a_custom_only_wallet_off_the_board_at_once(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    _give_history(v, X)
    public.scout_custom_add(X)
    R.tick(v, settings(), EQUITY, db_path=db)
    assert _row(X) is not None
    assert public.scout_custom_remove(X) is True
    assert _row(X) is None
    assert store.universe_row(conn, X) is None
    assert public.scout_presets().custom == 0
    assert store.stats_row(conn, X) is not None            # cache kept: re-adding is instant
    cw = public.scout_custom_add(X)
    assert cw is not None and cw.queued
    R.tick(v, settings(), EQUITY, db_path=db)
    assert _row(X) is not None and _row(X).custom


def test_custom_wallet_counts_as_on_board_for_the_trader_file(w):
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    _give_history(v, X)
    public.scout_custom_add(X)
    R.tick(v, settings(), EQUITY, db_path=db)
    assert store.request_row(conn, X) is None
    prof = public.scout_profile(X)
    assert hasattr(prof, "row")                            # a file, not a queued status
    assert store.request_row(conn, X) is None              # not re-queued as an off-board file


def test_a_request_during_a_long_refresh_is_served_before_it_ends(w, monkeypatch):
    """The scheduler used to serve the queue only between refreshes. A trader file or
    custom wallet asked for during a 45-minute refresh sat at "usually under a minute"
    the whole time. The refresh now drains the queue between two of its own wallets."""
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    _give_history(v, X)
    seen = {"built_at": None, "calls": 0, "on_board_during": False}
    orig = v.portfolio

    def hooked(user):
        seen["calls"] += 1
        if seen["calls"] == 2 and user != X:              # mid-refresh: the user adds a wallet
            public.scout_custom_add(X)
        if user != X and store.stats_row(conn, X) and seen["built_at"] is None:
            seen["built_at"] = seen["calls"]
            seen["on_board_during"] = _row(X) is not None
        return orig(user)

    monkeypatch.setattr(v, "portfolio", hooked)
    store.meta_set(conn, {"last_a_ms": 0, "last_b_ms": 0})
    R.tick(v, settings(), EQUITY, db_path=db)
    assert seen["built_at"] is not None and seen["built_at"] < seen["calls"], seen   # built while others still ran
    assert seen["on_board_during"], "the board was republished with it before the refresh ended"
    assert store.request_row(conn, X) is None
    assert _row(X) is not None and _row(X).custom
