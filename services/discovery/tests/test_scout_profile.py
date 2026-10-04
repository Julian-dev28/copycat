"""Trader file, fills paging, live orders cache, and the what-if path."""
from __future__ import annotations

import threading

import pytest
from discovery.scout import public
from test_scout_world import EQUITY, A, q, settings, world

from contracts.models import LeaderOverride, PnlWindow, SizingMode, TraderProfile


@pytest.fixture
def w(tmp_path, monkeypatch):
    return world(tmp_path, monkeypatch)


def test_profile_assembles_every_section(w):
    p = public.scout_profile(A)
    assert isinstance(p, TraderProfile)
    assert p.row.score.copy_fit is not None and p.row.address == A
    assert set(p.pnl_curve) == set(PnlWindow) and p.value_curve[PnlWindow.month]
    assert [r.window.value for r in p.risk] == ["7d", "30d", "all"]
    assert [t.window.value for t in p.trades] == ["7d", "30d"]
    assert p.sim_curve[0].value == EQUITY and len(p.sim_curve) >= 30
    assert p.daily_pnl and p.longest_win_streak_days >= 1 and p.coins[0].coin == "BTC"
    assert len(p.recent_trips) == 20 and p.recent_trips[0].closed_ms > p.recent_trips[-1].closed_ms
    assert len(p.recent_fills) == 40 and p.account.perps_usd == 20_000.0 and p.positions == []


def test_fills_paging_newest_first(w):
    first = public.scout_fills(A, None, 15)
    nxt = public.scout_fills(A, first[-1].time_ms, 15)
    assert len(first) == 15 and first[0].time_ms > first[-1].time_ms > nxt[0].time_ms
    assert len(public.scout_fills(A, None, 1000)) == 40 and public.scout_fills("junk", None, 5) == []


def test_orders_live_cached_and_failure_raises(w):
    v = w["venue"]
    v._orders[A] = [{"coin": "BTC", "side": "A", "limitPx": "89000.0", "sz": "1.0", "oid": 1, "timestamp": 5,
                     "isTrigger": False, "triggerPx": "0.0", "reduceOnly": False, "orderType": "Limit",
                     "origSz": "1.0", "tif": "Gtc"}]
    o = public.scout_orders(A)
    assert o[0]["px"] == 89000.0 and o[0]["coin"] == "BTC"
    public.scout_orders(A)
    assert v.orders_calls == [A]                         # second read served from the 30 s cache
    with pytest.raises(public.ScoutReadError):
        public.scout_orders("0x" + "ab" * 20)            # venue returns None: never "no orders"


def test_what_if_uses_cache_only_and_follows_override(w):
    v = w["venue"]
    n_fills, n_candles = len(v.fills_calls), len(v.candles_calls)
    base = public.scout_page(q()).rows
    row = next(r for r in base if r.address == A)
    same = public.scout_what_if(A, settings(), EQUITY, LeaderOverride())
    assert (len(v.fills_calls), len(v.candles_calls)) == (n_fills, n_candles)          # zero HL calls
    assert same.score.sim_return_pct == pytest.approx(row.score.sim_return_pct)
    assert same.score.copy_fit is None and same.sim_curve[0].value == EQUITY
    double = public.scout_what_if(A, settings(), EQUITY, LeaderOverride(fixed_margin_usd=2.0))
    assert double.score.sim_fees_usd == pytest.approx(2 * same.score.sim_fees_usd)
    prop = public.scout_what_if(A, settings(), 50.0, LeaderOverride(sizing_mode=SizingMode.fixed_notional,
                                                                     fixed_notional_usd=11.0))
    assert prop.sim_curve[0].value == 50.0


def test_what_if_one_at_a_time_and_unknown_wallet(w):
    with pytest.raises(LookupError):
        public.scout_what_if("0x" + "cd" * 20, settings(), EQUITY)
    public._what_if_lock.acquire()
    try:
        with pytest.raises(public.ScoutBusy):
            public.scout_what_if(A, settings(), EQUITY)
    finally:
        public._what_if_lock.release()
    assert isinstance(public._what_if_lock, type(threading.Lock()))
