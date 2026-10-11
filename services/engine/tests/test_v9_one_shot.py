"""Contract v9 one-shot wallets (LeaderOverride.one_shot, set by an MCP copy
plan with follow=false): copy only what he held when first seen, same side;
afterwards no new opens, no adds, no flips' new side; exits always mirror.

Hand numbers as in test_v8_direction: proportional, our equity $10,000,
sleeve 0.5, his equity $1,000,000. 1000 @ 100 = $100,000 of his -> $500 = 5.0 at mid 100.
"""
from __future__ import annotations

from engine import core
from engine_fakes import LEADER1, OUR

from contracts.models import LeaderOverride, Settings

EQ = 10_000.0


def cfg(one_shot=True, invested_ms=1, **kw) -> Settings:
    base = dict(enabled=True, dry_run=False, leaders=[LEADER1], sleeve_frac=0.5,
                max_position_leverage=50, leverage_mode="max", margin_mode="isolated",
                max_worse_entry_pct=10.0, min_order_bump=True, sizing_mode="proportional",
                size_multiplier=1.0,
                leader_overrides={LEADER1: LeaderOverride(one_shot=one_shot, invested_ms=invested_ms)})
    base.update(kw)
    return Settings(**base)


def run(venue, settings, state, now_ms=0):
    events = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append)
    out["_events"] = events
    return out


def ours(venue, coin, szi, entry=100.0):
    venue.hold(OUR, coin, szi, entry_px=entry, equity_perp_usd=EQ, available={"": EQ, "xyz": EQ})


def setup(venue):
    venue.set_account(OUR, EQ, available={"": EQ, "xyz": EQ})


def test_copies_what_he_holds_then_nothing_new(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER1, "ETH", -1000.0, entry_px=100.0)
    out = run(venue, cfg(), engine_state, 0)
    assert sorted(out["opened"]) == ["BTC", "ETH"]
    base = [e for e in out["_events"] if e.action == "baseline"]
    assert base and "one-shot" in base[0].reason and "BTC long" in base[0].reason \
        and "ETH short" in base[0].reason
    assert engine_state.get_kv("one_shot")[LEADER1]["coins"] == {"BTC": 1, "ETH": -1}
    ours(venue, "BTC", 5.0)
    ours(venue, "ETH", -5.0)
    n = len(venue.orders)
    venue.hold(LEADER1, "SOL", 1000.0, entry_px=100.0)              # a new position: not copied
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)              # an add: not copied
    out = run(venue, cfg(), engine_state, 1)
    assert out["skipped"]["SOL"] == "one-shot: only the positions he held when copied"
    assert out["skipped"]["BTC"] == "one-shot: adds not copied"
    assert len(venue.orders) == n
    venue.hold(LEADER1, "ETH", 0.0)                                 # exit: mirrored
    out = run(venue, cfg(), engine_state, 2)
    assert out["closed"] == ["ETH"]
    assert engine_state.get_kv("one_shot")[LEADER1]["coins"] == {"BTC": 1}


def test_a_closed_coin_reopened_later_is_not_copied(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 0)
    ours(venue, "BTC", 5.0)
    venue.hold(LEADER1, "BTC", 0.0)
    run(venue, cfg(), engine_state, 1)
    venue.accounts[OUR]["positions"].pop("BTC", None)
    n = len(venue.orders)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(), engine_state, 2)
    assert out["skipped"]["BTC"] == "one-shot: only the positions he held when copied"
    assert len(venue.orders) == n


def test_a_flip_closes_and_does_not_open_the_new_side(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 0)
    ours(venue, "BTC", 5.0)
    venue.hold(LEADER1, "BTC", -1000.0, entry_px=100.0)
    out = run(venue, cfg(), engine_state, 1)
    assert out["closed"] == ["BTC"] and not out["opened"]
    assert out["skipped"]["BTC"] == "one-shot: only the positions he held when copied"


def test_a_held_position_waiting_on_entry_deviation_still_opens_later(engine_state, venue):
    """The plan's entry deviation: a held position whose mid is too far from his
    entry waits (pending) and opens once price comes back."""
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.mids["BTC"] = 120.0                                       # 20% worse than his entry
    out = run(venue, cfg(), engine_state, 0)
    assert "worse than entry" in out["skipped"]["BTC"] and not venue.orders
    venue.mids["BTC"] = 101.0
    out = run(venue, cfg(), engine_state, 1)
    assert out["opened"] == ["BTC"]


def test_turning_one_shot_off_drops_the_record_and_follows_again(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 0)
    ours(venue, "BTC", 5.0)
    run(venue, cfg(one_shot=False), engine_state, 1)
    assert LEADER1 not in (engine_state.get_kv("one_shot") or {})
    venue.hold(LEADER1, "SOL", 1000.0, entry_px=100.0)
    out = run(venue, cfg(one_shot=False), engine_state, 2)
    assert out["opened"] == ["SOL"]


def test_a_new_investment_takes_a_new_snapshot(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(invested_ms=1), engine_state, 0)
    venue.hold(LEADER1, "SOL", 1000.0, entry_px=100.0)
    run(venue, cfg(invested_ms=5), engine_state, 1)
    assert engine_state.get_kv("one_shot")[LEADER1] == {"invested_ms": 5,
                                                        "coins": {"BTC": 1, "SOL": 1}}


def test_wallets_without_one_shot_are_untouched(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(one_shot=None), engine_state, 0)
    assert out["opened"] == ["BTC"] and engine_state.get_kv("one_shot") is None


def test_leader_book_is_one_account_read_entry_based(venue):
    import pytest

    from engine import public
    venue.hold(LEADER1, "ETH", -2.0, entry_px=3000.0)
    venue.hold(LEADER1, "BTC", 0.5, entry_px=60_000.0)
    venue.mids["BTC"] = 99_999.0                                  # marks never enter it
    assert public.leader_book(LEADER1, venue=venue) == [
        {"coin": "BTC", "side": "long", "notional_usd": 30_000.0},
        {"coin": "ETH", "side": "short", "notional_usd": 6000.0}]
    venue.accounts[LEADER1] = None
    with pytest.raises(public.PreviewUnavailable):
        public.leader_book(LEADER1, venue=venue)
