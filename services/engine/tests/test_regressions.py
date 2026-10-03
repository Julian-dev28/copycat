"""Regression tests for the 2026-10-03 review findings, one block per
finding. Each test fails on the pre-fix engine. <2s, FakeVenue only."""
from __future__ import annotations

import pytest

from engine import core

from engine_fakes import LEADER1, LEADER2, OUR

from test_core import cfg, run


def _open(venue, state, coin="BTC", leader=LEADER1, szi=1000.0, **kw):
    venue.hold(leader, coin, szi, entry_px=100.0)
    out = run(venue, cfg(**kw), state)
    assert coin in out["opened"]
    return out


# ── 1. copy exists + leader prev == 0 crashed every cycle (ZeroDivisionError) ─

def test_live_copy_then_dry_exit_then_live_reopen_never_divides_by_zero(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 0.0)
    run(venue, cfg(leaders=[LEADER1], dry_run=True), engine_state, now_ms=1)
    venue.hold(LEADER1, "BTC", 500.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["reduced"] == ["BTC"]       # 1000 -> 500 as seen from live: half off, no crash


@pytest.mark.parametrize("mode,expect_add", [("proportional", True), ("fixed_margin", False),
                                              ("fixed_notional", False)])
def test_add_with_a_flat_previous_size_is_sized_or_skipped_never_crashes(engine_state, venue,
                                                                         mode, expect_add):
    from engine.state import Copy, LeaderState
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    engine_state.put_copy(Copy("BTC", LEADER1, 0, 3, False, mode))
    engine_state.put_leader(LeaderState(LEADER1, {}, [], 0))      # his last size: flat
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode=mode), engine_state, now_ms=1)
    assert (out["added"] == ["BTC"]) is expect_add
    if not expect_add:
        assert "no fraction to scale" in out["skipped"]["BTC"]


def test_one_leader_raising_does_not_block_the_next_leaders_exit(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, coin="ETH", leader=LEADER2, leaders=[LEADER1, LEADER2])
    venue.hold(OUR, "ETH", 0.5, entry_px=100.0)
    venue.hold(LEADER2, "ETH", 0.0)
    venue.hold(LEADER1, "SOL", 10.0, entry_px=100.0)

    def boom(user):
        if user == LEADER1:
            raise RuntimeError("extras exploded")
        return {"spot_other_usd": 0.0, "staked_hype_usd": 0.0}
    venue.extras = boom
    events = []
    out = core.run_cycle(cfg(leaders=[LEADER1, LEADER2], include_spot_staked=True), venue,
                         engine_state, OUR, 1, events.append)
    assert out["closed"] == ["ETH"]
    assert out["skipped"][f"leader:{LEADER1}"] == "leader cycle raised, see logs"
    assert any(e.action == "error" and e.leader == LEADER1 for e in events)


def test_one_coin_raising_does_not_block_the_same_leaders_other_exits(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)
    _open(venue, engine_state, coin="BTC", leaders=[LEADER1])
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(OUR, "ETH", 0.5, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.hold(LEADER1, "ETH", 400.0, entry_px=100.0)      # reduce needs mid -> raises
    venue.raise_on_mid.add("ETH")
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["closed"] == ["BTC"]
    assert out["skipped"]["ETH"] == "coin step raised, see logs"
    assert engine_state.get_leader(LEADER1).last_positions["ETH"] == 1000.0   # exit retried


# ── 2. toggling dry_run stranded real copies ────────────────────────────────

def test_leader_exit_during_dry_run_is_mirrored_once_live_again(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 0.0)
    out = run(venue, cfg(leaders=[LEADER1], dry_run=True), engine_state, now_ms=1)
    assert not venue.closes and out["skipped"]["BTC"].startswith("real copy held")
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["closed"] == ["BTC"] and engine_state.all_copies() == []


def test_a_stranded_copy_whose_leader_is_already_flat_is_closed(engine_state, venue):
    from engine.state import Copy, LeaderState
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.set_account(LEADER1, 1_000_000.0)
    engine_state.put_copy(Copy("BTC", LEADER1, 0, 3, False, "fixed_margin"))
    engine_state.put_leader(LeaderState(LEADER1, {}, [], 0))   # he is flat and so is his last
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["closed"] == ["BTC"]


def test_stranded_close_needs_a_good_leader_read(engine_state, venue):
    from engine.state import Copy, LeaderState
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.fail_account(LEADER1)
    engine_state.put_copy(Copy("BTC", LEADER1, 0, 3, False, "fixed_margin"))
    engine_state.put_leader(LeaderState(LEADER1, {}, [], 0))
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert not venue.closes


# ── 3. unknown fills: pending-row protocol ──────────────────────────────────

def test_open_writes_a_pending_row_before_the_order_and_sends_its_cloid(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    seen = {}
    real_market = venue.market

    def spy(coin, is_buy, size, mid, reduce_only=False, cloid=None, max_slippage_pct=1.0):
        seen["row"] = engine_state.get_copy(coin)
        return real_market(coin, is_buy, size, mid, reduce_only, cloid, max_slippage_pct)
    venue.market = spy
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    cloid = venue.cloids[0]
    assert seen["row"] is not None and seen["row"].pending_cloid == cloid
    assert cloid.startswith("0x") and len(cloid) == 34
    assert engine_state.get_copy("BTC").pending_cloid is None      # promoted on fill


def test_ambiguous_open_keeps_a_pending_row_promoted_when_we_hold_it(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.ambiguous.add("BTC")
    out = run(venue, cfg(leaders=[LEADER1]), engine_state)
    assert out["opened"] == [] and engine_state.get_copy("BTC").pending_cloid
    venue.ambiguous.clear()
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)                     # it did fill
    events = []
    core.run_cycle(cfg(leaders=[LEADER1]), venue, engine_state, OUR, 1, events.append)
    assert engine_state.get_copy("BTC").pending_cloid is None
    assert any(e.action == "open" and "ambiguous" in e.reason for e in events)
    assert len(venue.orders) == 1                                   # never re-sent


def test_ambiguous_open_that_never_filled_is_dropped_once_hl_settles_it(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.ambiguous.add("BTC")
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    cloid = engine_state.get_copy("BTC").pending_cloid
    venue.statuses[cloid] = None                                    # status read failed: wait
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert engine_state.get_copy("BTC") is not None
    venue.statuses[cloid] = "canceled"
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert engine_state.get_copy("BTC") is None
    assert "BTC" in engine_state.get_leader(LEADER1).ignored        # no re-entry mid-position
    assert len(venue.orders) == 1


def test_a_crash_between_market_and_the_result_leaves_a_resolvable_row(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    real_market = venue.market

    def dies_after_sending(*a, **kw):
        real_market(*a, **kw)
        raise ConnectionError("process died mid-request")
    venue.market = dies_after_sending
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    assert engine_state.get_copy("BTC").pending_cloid               # tracked, not "not ours"
    venue.market = real_market
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert engine_state.get_copy("BTC").pending_cloid is None


def test_ambiguous_reduce_is_never_resent_blind_and_settles_from_our_real_size(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 500.0)                               # half off
    venue.ambiguous.add("BTC")
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert venue.orders[-1] == ("BTC", False, 1.0, True)
    cloid = venue.cloids[-1]
    venue.ambiguous.clear()
    venue.statuses[cloid] = None
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert len(venue.orders) == 2                                   # unresolved: nothing sent
    venue.statuses[cloid] = "filled"
    venue.hold(OUR, "BTC", 1.0, entry_px=100.0)                     # it did fill
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=3)
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=4)
    assert len(venue.orders) == 2                                   # no double reduce
    assert engine_state.get_leader(LEADER1).last_positions["BTC"] == 500.0


def test_ambiguous_reduce_that_did_not_fill_is_retried_once_settled(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 500.0)
    venue.ambiguous.add("BTC")
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    venue.ambiguous.clear()
    venue.statuses[venue.cloids[-1]] = "canceled"                   # our size still 2.0
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["reduced"] == ["BTC"] and venue.orders[-1] == ("BTC", False, 1.0, True)


# ── 4. partial fills (contract v2: ok False + filled_sz) ────────────────────

def test_partial_open_is_a_real_confirmed_copy(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.fill_frac["BTC"] = 0.3
    out = run(venue, cfg(leaders=[LEADER1]), engine_state)
    assert out["opened"] == ["BTC"]
    assert engine_state.get_copy("BTC").pending_cloid is None


def test_ambiguous_close_keeps_the_copy_and_retries(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.close_ambiguous.add("BTC")
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert engine_state.get_copy("BTC") is not None and "outcome unknown" in out["skipped"]["BTC"]
    venue.close_ambiguous.clear()
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["closed"] == ["BTC"]


# ── 7. reduces are never bumped; small ones accumulate ──────────────────────

def test_a_reduce_under_the_minimum_accumulates_instead_of_being_bumped(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    _open(venue, engine_state, leaders=[LEADER1])
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)                     # $200
    venue.hold(LEADER1, "BTC", 960.0)                               # 4% off = $8
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert len(venue.orders) == 1 and "accumulating" in out["skipped"]["BTC"]
    assert engine_state.get_leader(LEADER1).last_positions["BTC"] == 1000.0
    venue.hold(LEADER1, "BTC", 900.0)                               # now 10% = $20
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["reduced"] == ["BTC"] and venue.orders[-1] == ("BTC", False, 0.2, True)


# ── 13. bump must not re-inflate past the margin room ───────────────────────

def test_min_order_bump_past_available_margin_is_skipped(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0, available={"": 1.0})
    venue.max_levs["BTC"] = 3
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state)
    assert out["opened"] == [] and not venue.orders
    assert "needs more margin than available" in out["skipped"]["BTC"]


# ── 14. dry_copies cleared when the mode flips ──────────────────────────────

def test_dry_copies_are_cleared_when_dry_run_flips(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], dry_run=True), engine_state)
    assert [d.coin for d in engine_state.all_dry_copies()] == ["BTC"]
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert engine_state.all_dry_copies() == []


def test_unknown_order_status_is_only_believed_after_the_grace_window(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.ambiguous.add("BTC")
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=0)
    venue.ambiguous.clear()                     # fake answers "unknown" for this cloid
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=5_000)
    assert engine_state.get_copy("BTC") is not None                 # HL may not have it yet
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=31_000)
    assert engine_state.get_copy("BTC") is None


def test_a_canceled_status_with_a_real_position_is_a_partial_fill_and_promoted(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.ambiguous.add("BTC")
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.statuses[engine_state.get_copy("BTC").pending_cloid] = "canceled"
    venue.hold(OUR, "BTC", 0.2, entry_px=100.0)                     # IOC filled 0.2 then canceled
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert engine_state.get_copy("BTC").pending_cloid is None
