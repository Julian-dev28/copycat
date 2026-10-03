"""engine.core.run_cycle: ported from pathiel's test_copycat.py (sibling
repo, commit ab2e800) onto contracts.models/contracts.venue + FakeVenue +
SQLite EngineState instead of pathiel's JSON-file state and claims
registry. Every test below either has a direct pathiel ancestor (noted in
its docstring) or covers one of the standalone-product-only behaviors
(daily_loss_limit_usd, max_open_copies, "not ours", dry_run) the task added
on top. <2s, no network -- FakeVenue only.
"""
from __future__ import annotations

from contracts.models import Settings

from engine import core

from engine_fakes import LEADER1, LEADER2, OUR


def cfg(**overrides) -> Settings:
    """Mirrors pathiel's test `cfg()`: sizing_mode pinned to "proportional"
    (the contract's own default is "fixed_margin") so every test below that
    was written against the proportional formula keeps pathiel's original
    numbers. `enabled=True, dry_run=False` because the contract ships both
    the opposite of that by default ("real money: ships OFF")."""
    base = dict(enabled=True, dry_run=False, leaders=[LEADER1, LEADER2], sleeve_frac=0.5,
                max_position_leverage=50, leverage_mode="max", margin_mode="isolated",
                include_spot_staked=False, only_new_positions=False, max_worse_entry_pct=10.0,
                min_order_bump=True, sizing_mode="proportional", size_multiplier=1.0)
    base.update(overrides)
    return Settings(**base)


def run(venue, settings, state, now_ms=0):
    events = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append)
    out["_events"] = events
    return out


# ── baseline (pathiel: test_baseline_only_new_positions_*) ──────────────────

def test_baseline_only_new_positions_true_ignores_what_he_already_holds(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 1000.0)
    run(venue, cfg(leaders=[LEADER1], only_new_positions=True), engine_state)
    venue.hold(LEADER1, "BTC", 2000.0)              # adds to the pre-existing position
    out = run(venue, cfg(leaders=[LEADER1], only_new_positions=True), engine_state, now_ms=1)
    assert not venue.orders and not out["opened"]


def test_baseline_only_new_positions_false_copies_his_existing_book_at_first_sight(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)   # $100k notional on $1M equity
    out = run(venue, cfg(leaders=[LEADER1], only_new_positions=False), engine_state)
    assert out["opened"] == ["BTC"]
    # allocation = 1000 equity * 0.5 sleeve / 1 leader = 500
    # his_added_ntl = 1000 * 100 = 100000; ntl = 100000/1e6*500 = 50; size = 50/100 mid = 0.5
    assert venue.orders == [("BTC", True, 0.5, False)]


# ── max_worse_entry_pct (pathiel: test_*_open_skipped_when_mid_is_worse_*) ──

def test_long_open_skipped_when_mid_is_worse_than_entry_and_retried_when_price_returns(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.mids["BTC"] = 115.0                        # >10% above his entry for a long
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=0)
    assert "worse than entry" in out["skipped"]["BTC"]
    assert not venue.orders

    venue.mids["BTC"] = 105.0                        # back within 10%
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["opened"] == ["BTC"]


def test_short_open_skipped_when_mid_is_worse_than_entry_and_retried_when_price_returns(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "ETH", -10.0, entry_px=100.0)
    venue.mids["ETH"] = 85.0                         # >10% below his entry for a short
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=0)
    assert "worse than entry" in out["skipped"]["ETH"]
    assert not venue.orders

    venue.mids["ETH"] = 95.0
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["opened"] == ["ETH"]


# ── leverage_mode (pathiel: test_leverage_mode_*) ────────────────────────────

def test_leverage_mode_max_opens_at_the_coin_max_capped_by_max_position_leverage(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 20
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0, lev=3.0)
    out = run(venue, cfg(leaders=[LEADER1], leverage_mode="max", max_position_leverage=50),
              engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.levs["BTC"]["leverage"] == 20


def test_leverage_mode_match_uses_the_leaders_leverage_ceiled_and_capped(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 20
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0, lev=7.2)
    out = run(venue, cfg(leaders=[LEADER1], leverage_mode="match", max_position_leverage=50),
              engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.levs["BTC"]["leverage"] == 8            # ceil(7.2) under coin max 20 and cap 50


def test_max_position_leverage_caps_match_mode_below_the_leaders_own_leverage(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 40
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0, lev=30.0)
    out = run(venue, cfg(leaders=[LEADER1], leverage_mode="match", max_position_leverage=10),
              engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.levs["BTC"]["leverage"] == 10


# ── margin_mode (pathiel: test_margin_mode_*, test_isolated_only_market_*) ──

def test_margin_mode_isolated_requests_is_cross_false(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], margin_mode="isolated"), engine_state)
    assert venue.levs["BTC"]["is_cross"] is False


def test_margin_mode_cross_requests_is_cross_true(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "ETH", 10.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], margin_mode="cross"), engine_state)
    assert venue.levs["ETH"]["is_cross"] is True


def test_isolated_only_market_forces_is_cross_false_regardless_of_request(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.isolated_only = {"XRP"}
    venue.hold(LEADER1, "XRP", 10.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], margin_mode="cross"), engine_state)
    assert venue.levs["XRP"]["is_cross"] is False
    assert {c.coin for c in engine_state.all_copies()} == {"XRP"}


# ── include_spot_staked (pathiel: test_include_spot_staked_*) ──────────────

def test_include_spot_staked_false_sizes_off_perp_plus_spot_usdc_only(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0, equity_perp_usd=900_000.0, spot_usdc=100_000.0)
    out = run(venue, cfg(leaders=[LEADER1], include_spot_staked=False), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] == 0.5


def test_include_spot_staked_true_adds_extras_to_his_equity_and_shrinks_the_size(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0, equity_perp_usd=900_000.0, spot_usdc=100_000.0)
    venue.extras_map[LEADER1] = {"spot_other_usd": 500_000.0, "staked_hype_usd": 500_000.0}
    out = run(venue, cfg(leaders=[LEADER1], include_spot_staked=True), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] == 0.25                     # his equity doubled -> half the size


def test_include_spot_staked_true_skips_the_leader_when_extras_read_fails(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.extras_map[LEADER1] = None
    out = run(venue, cfg(leaders=[LEADER1], include_spot_staked=True), engine_state)
    assert out["skipped"].get(f"leader:{LEADER1}") == "extras read failed"
    assert not venue.orders


# ── multi-leader ownership (pathiel: test_two_leaders_*, test_a_failed_leader_*,
#    test_a_leader_removed_from_config_*) ───────────────────────────────────

def test_two_leaders_on_the_same_coin_first_in_config_order_owns_it(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.hold(LEADER2, "BTC", 20.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1, LEADER2]), engine_state)
    assert out["opened"] == ["BTC"]
    assert out["skipped"]["BTC"] == f"owned by leader {LEADER1}"
    assert len(venue.orders) == 1

    venue.hold(LEADER1, "BTC", 0.0)                       # leader1 goes flat -> our copy closes
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    out2 = run(venue, cfg(leaders=[LEADER1, LEADER2]), engine_state, now_ms=1)
    assert out2["closed"] == ["BTC"]
    assert engine_state.all_copies() == []
    assert "BTC" not in out2.get("opened", [])


def test_a_failed_leader_read_skips_only_that_leader(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.hold(LEADER2, "ETH", 10.0, entry_px=100.0)
    venue.fail_account(LEADER1)
    out = run(venue, cfg(leaders=[LEADER1, LEADER2]), engine_state)
    assert out["skipped"][f"leader:{LEADER1}"] == "leader read failed"
    assert out["opened"] == ["ETH"]


def test_a_leader_removed_from_config_still_mirrors_his_exits_but_opens_nothing_new(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1, LEADER2]), engine_state)
    assert {c.coin for c in engine_state.all_copies()} == {"BTC"}

    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)   # removed from config, adds -- not mirrored
    venue.hold(OUR, "BTC", 5.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER2]), engine_state, now_ms=1)
    assert out["skipped"]["BTC"] == "orphan leader: no new exposure"
    assert not out["added"]

    venue.hold(LEADER1, "BTC", 0.0)                       # he goes flat -- must still close
    out2 = run(venue, cfg(leaders=[LEADER2]), engine_state, now_ms=2)
    assert out2["closed"] == ["BTC"]
    assert engine_state.all_copies() == []


# ── exit mirroring: reduce / close / flip / retry (pathiel: test_a_partial_close_*,
#    test_his_flat_is_our_flat, test_a_flip_*, test_a_failed_close_*,
#    test_our_copy_vanished_*) ───────────────────────────────────────────────

def test_a_partial_close_takes_the_same_fraction_off_ours(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.hold(LEADER1, "BTC", 250.0)                     # he takes 75% off
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["reduced"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", False, 1.5, True)


def test_his_flat_is_our_flat(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["closed"] == ["BTC"] and venue.closes == ["BTC"]
    assert engine_state.all_copies() == []


def test_a_flip_closes_then_opens_fresh(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.hold(LEADER1, "BTC", -500.0, entry_px=100.0)    # flips long -> short
    venue.hold(OUR, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["closed"] == ["BTC"]
    assert out["opened"] == ["BTC"]
    assert venue.closes == ["BTC"]


def test_a_failed_close_is_retried_next_cycle(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.fail_close = True
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    venue.fail_close = False
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["closed"] == ["BTC"]


def test_our_copy_vanished_stops_mirroring_until_he_goes_flat_and_reopens(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)

    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)    # he adds; our copy is gone by hand
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    # first missing read: pending, nothing traded, row kept
    assert out["skipped"]["BTC"].startswith("our copy is missing")
    assert not venue.orders[1:] and len(engine_state.all_copies()) == 1
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    # second missing read: confirmed and forgotten
    assert out["vanished"] == ["BTC"]
    assert engine_state.all_copies() == []

    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)    # still ignored while he holds it
    out_ignored = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=3)
    assert not out_ignored["opened"]

    venue.hold(LEADER1, "BTC", 0.0)                       # he goes flat -- clears the ignore
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=4)

    venue.hold(LEADER1, "BTC", 500.0, entry_px=100.0)     # he reopens -- copyable again
    out2 = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=5)
    assert out2["opened"] == ["BTC"]


# ── entries gating: daily loss / disabled (pathiel: test_the_daily_loss_gate_*,
#    test_disabled_still_mirrors_exits_*) ───────────────────────────────────

_DAY0 = 0            # 1970-01-01 UTC
_DAY0_LATER = 1000   # same UTC day as _DAY0


def test_the_daily_loss_gate_blocks_the_open_and_the_whole_trip(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=_DAY0)   # seeds the day anchor at 1,000,000

    venue.set_account(OUR, 999_700.0)             # day PnL now -300, past the -100 limit below
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], daily_loss_limit_usd=-100.0), engine_state,
              now_ms=_DAY0_LATER)
    assert out["halted_reason"] is not None
    assert not venue.orders

    venue.set_account(OUR, 1_000_000.0)           # gate clear now, trip already missed
    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)
    out2 = run(venue, cfg(leaders=[LEADER1], daily_loss_limit_usd=-100.0), engine_state,
               now_ms=_DAY0_LATER + 1)
    assert not venue.orders and not out2["opened"]


def test_daily_loss_halt_blocks_opens_but_never_blocks_exits(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], daily_loss_limit_usd=-100.0), engine_state, now_ms=_DAY0)
    assert {c.coin for c in engine_state.all_copies()} == {"BTC"}   # opened while the gate was clear

    venue.hold(LEADER1, "BTC", 0.0)                # he exits
    venue.hold(OUR, "BTC", 500.0, entry_px=100.0,
               equity_perp_usd=900_000.0)          # day PnL now -100,000 -- well past the limit
    out = run(venue, cfg(leaders=[LEADER1], daily_loss_limit_usd=-100.0), engine_state,
              now_ms=_DAY0_LATER)
    assert out["halted_reason"] is not None
    assert out["closed"] == ["BTC"]
    assert venue.closes == ["BTC"]


def test_disabled_still_mirrors_exits_but_opens_nothing(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], enabled=False), engine_state, now_ms=1)
    assert out["closed"] == ["BTC"]


# ── min_order_bump (pathiel: test_min_order_bump_*, test_below_the_bump_floor_*) ─

def test_min_order_bump_rounds_a_small_notional_up_to_the_exchange_minimum(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 100.0, entry_px=100.0)     # ntl = 10000/1e6*500 = 5.0
    out = run(venue, cfg(leaders=[LEADER1], min_order_bump=True), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] * 100.0 == 10.5


def test_below_the_bump_floor_is_skipped_even_with_min_order_bump_on(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 40.0, entry_px=100.0)      # ntl = 4000/1e6*500 = 2.0, under 25% of 10.5
    out = run(venue, cfg(leaders=[LEADER1], min_order_bump=True), engine_state)
    assert "minimum" in out["skipped"]["BTC"]
    assert not venue.orders


def test_min_order_bump_off_skips_the_same_small_notional(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 100.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], min_order_bump=False), engine_state)
    assert "minimum" in out["skipped"]["BTC"]
    assert not venue.orders


# ── "not ours": no claims registry here, a real foreign position is never
#    touched (replaces pathiel's cross-book claims test) ───────────────────

def test_a_real_position_we_did_not_open_is_never_touched(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(OUR, "BTC", 3.0, entry_px=90.0)             # a manual/pre-existing position, not ours
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state)
    assert "not ours" in out["skipped"]["BTC"]
    assert not venue.orders
    assert engine_state.get_copy("BTC") is None


def test_adding_to_an_already_owned_copy_is_unaffected_by_the_not_ours_check(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1]), engine_state)       # opens BTC for real, via LEADER1
    assert engine_state.get_copy("BTC") is not None

    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)     # he adds
    venue.hold(OUR, "BTC", 500.0, entry_px=100.0)          # our own position now exists (we opened it)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["added"] == ["BTC"]


# ── max_open_copies (new risk control) ───────────────────────────────────────

def test_max_open_copies_blocks_a_new_open_once_the_cap_is_hit(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER2, "ETH", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1, LEADER2], max_open_copies=1), engine_state)
    assert out["opened"] == ["BTC"]                         # LEADER1 processed first (config order)
    assert "max_open_copies reached" in out["skipped"]["ETH"]
    assert len(venue.orders) == 1
    assert {c.coin for c in engine_state.all_copies()} == {"BTC"}


def test_max_open_copies_does_not_block_an_add_to_an_existing_copy(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], max_open_copies=1), engine_state)
    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)
    venue.hold(OUR, "BTC", 500.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], max_open_copies=1), engine_state, now_ms=1)
    assert out["added"] == ["BTC"]


# ── sizing_mode behavior (pathiel: test_sizing_mode_*, test_size_multiplier_*,
#    test_fixed_*_add_scales_*) ─────────────────────────────────────────────

def test_sizing_mode_fixed_margin_opens_at_fixed_margin_times_leverage(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.max_levs["BTC"] = 40
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode="fixed_margin", fixed_margin_usd=1.0,
                         leverage_mode="max", max_position_leverage=50), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] * venue.mid("BTC") == 40.0    # $1.00 margin * 40x leverage
    assert venue.levs["BTC"]["leverage"] == 40


def test_sizing_mode_fixed_margin_default_needs_the_bump_for_a_tiny_account(engine_state, venue):
    """The exact motivating scenario: a $1.29 account, defaults all the way
    (fixed_margin_usd=0.25, leverage_mode "max" -> 40x here -> raw notional
    $10.00, just under the exchange floor -- min_order_bump rescues it."""
    venue.set_account(OUR, 1.29)
    venue.max_levs["BTC"] = 40
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode="fixed_margin", fixed_margin_usd=0.25,
                         leverage_mode="max", max_position_leverage=50), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] * venue.mid("BTC") == 10.5


def test_sizing_mode_fixed_notional_opens_at_the_fixed_dollar_amount(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode="fixed_notional", fixed_notional_usd=25.0),
              engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.orders[0][2] * venue.mid("BTC") == 25.0


def test_size_multiplier_scales_proportional_mode_only(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode="proportional", size_multiplier=3.0),
              engine_state)
    assert out["opened"] == ["BTC"]
    # baseline proportional notional at mult=1 is $50 (same setup as the
    # only_new_positions=False test above) -- x3 size_multiplier -> $150.
    assert venue.orders[0][2] * venue.mid("BTC") == 150.0


def test_fixed_margin_add_scales_our_position_by_his_fractional_change(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.max_levs["BTC"] = 10
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    cfg_fm = cfg(leaders=[LEADER1], sizing_mode="fixed_margin", fixed_margin_usd=5.0,
                 leverage_mode="max", max_position_leverage=50)
    run(venue, cfg_fm, engine_state)
    assert venue.orders[-1][2] == 0.5                       # open: $5 margin * 10x / $100 mid

    venue.hold(LEADER1, "BTC", 15.0, entry_px=100.0)         # he adds 50%
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    out = run(venue, cfg_fm, engine_state, now_ms=1)
    assert out["added"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 0.25, False)    # our_add = 0.5 * 0.5 = 0.25 BTC


def test_fixed_notional_add_scales_our_position_by_his_fractional_change(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    cfg_fn = cfg(leaders=[LEADER1], sizing_mode="fixed_notional", fixed_notional_usd=20.0)
    run(venue, cfg_fn, engine_state)
    assert venue.orders[-1][2] == 0.2                        # open: $20 / $100 mid

    venue.hold(LEADER1, "BTC", 20.0, entry_px=100.0)          # he doubles his size
    venue.hold(OUR, "BTC", 0.2, entry_px=100.0)
    out = run(venue, cfg_fn, engine_state, now_ms=1)
    assert out["added"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 0.2, False)      # our_add = 0.2 * 1.0 = 0.2 BTC


# ── leverage_mode "fixed" (pathiel: test_leverage_mode_fixed_*) ─────────────

def test_leverage_mode_fixed_uses_the_configured_leverage(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 40
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], leverage_mode="fixed", leverage=15,
                         max_position_leverage=50), engine_state)
    assert out["opened"] == ["BTC"]
    assert venue.levs["BTC"]["leverage"] == 15


def test_leverage_mode_fixed_is_still_capped_by_the_coin_max(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 10
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], leverage_mode="fixed", leverage=45, max_position_leverage=50),
        engine_state)
    assert venue.levs["BTC"]["leverage"] == 10


def test_leverage_mode_fixed_is_still_capped_by_max_position_leverage(engine_state, venue):
    venue.set_account(OUR, 100_000.0)
    venue.max_levs["BTC"] = 40
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], leverage_mode="fixed", leverage=45, max_position_leverage=20),
        engine_state)
    assert venue.levs["BTC"]["leverage"] == 20


# ── sizing_mode/leverage recorded in state + log_event (pathiel:
#    test_open_records_the_effective_sizing_mode_*) ─────────────────────────

def test_open_records_the_effective_sizing_mode_in_state_and_log_event(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], sizing_mode="fixed_notional", fixed_notional_usd=20.0),
              engine_state)
    assert out["opened"] == ["BTC"]
    open_events = [e for e in out["_events"] if e.action == "open"]
    assert open_events and open_events[0].coin == "BTC"
    assert open_events[0].leverage == venue.levs["BTC"]["leverage"]

    copy = engine_state.get_copy("BTC")
    assert copy.sizing_mode == "fixed_notional"


# ── per-leader overrides, end to end through Settings.for_leader ───────────

def test_leader_override_changes_effective_sizing_for_that_leader_only(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.hold(LEADER2, "ETH", 10.0, entry_px=100.0)
    cfg_ov = cfg(leaders=[LEADER1, LEADER2], sizing_mode="fixed_notional", fixed_notional_usd=20.0,
                 leader_overrides={LEADER2: {"fixed_notional_usd": 40.0}})
    out = run(venue, cfg_ov, engine_state)
    assert sorted(out["opened"]) == ["BTC", "ETH"]
    btc_order = next(o for o in venue.orders if o[0] == "BTC")
    eth_order = next(o for o in venue.orders if o[0] == "ETH")
    assert btc_order[2] * venue.mid("BTC") == 20.0           # LEADER1: book-wide default
    assert eth_order[2] * venue.mid("ETH") == 40.0           # LEADER2: overridden


# ── dry_run: real reads, no writes, intents, no state corruption ───────────

def test_dry_run_emits_intents_and_never_touches_real_copy_state(engine_state, venue):
    # fixed_notional so the open clears $10.50: proportional at this equity is $0.50.
    dcfg = lambda: cfg(leaders=[LEADER1], dry_run=True, sizing_mode="fixed_notional",
                       fixed_notional_usd=20.0)
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    out = run(venue, dcfg(), engine_state, now_ms=0)
    assert out["opened"] == ["BTC"]                 # the engine's own bookkeeping of what happened
    assert venue.orders == [] and venue.closes == []  # but genuinely NO real write ever fired
    assert engine_state.all_copies() == []            # the REAL table stays untouched
    dry = engine_state.all_dry_copies()
    assert len(dry) == 1 and dry[0].coin == "BTC"
    intents = [e for e in out["_events"] if e.action == "intent"]
    assert intents and intents[0].reason == "would open"

    venue.hold(LEADER1, "BTC", 20.0, entry_px=100.0)   # he adds -- classified correctly off the shadow row
    out2 = run(venue, dcfg(), engine_state, now_ms=1)
    assert out2["added"] == ["BTC"]
    assert engine_state.all_copies() == []
    intents2 = [e for e in out2["_events"] if e.action == "intent"]
    assert intents2[0].reason == "would add"

    venue.hold(LEADER1, "BTC", 0.0)                    # he exits -- closed as an intent too
    out3 = run(venue, dcfg(), engine_state, now_ms=2)
    assert out3["closed"] == ["BTC"]
    assert venue.closes == []                           # still never a real close
    assert engine_state.all_dry_copies() == []
    intents3 = [e for e in out3["_events"] if e.action == "intent"]
    assert intents3[0].reason == "would close"


def test_dry_run_blocks_exits_too_no_writes_means_no_writes(engine_state, venue):
    """dry_run is a stricter axis than `enabled=False`: a REAL copy opened
    while live stays unmirrored (no real close) once dry_run flips on, and
    is reported only as an intent."""
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER1], dry_run=False), engine_state, now_ms=0)
    assert engine_state.get_copy("BTC") is not None

    venue.hold(LEADER1, "BTC", 0.0)
    venue.hold(OUR, "BTC", 5.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], dry_run=True), engine_state, now_ms=1)
    assert venue.closes == []                           # no real close fired
    assert out["skipped"]["BTC"].startswith("real copy held")   # deferred, not forgotten
    assert engine_state.get_copy("BTC") is not None      # the REAL copy row is untouched by dry_run


# ── skip events: visible in the feed, not spammed ───────────────────────────

def test_a_skip_is_logged_once_and_again_only_when_its_reason_changes(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 10.0, entry_px=100.0)
    venue.mids["BTC"] = 150.0                           # 50% worse than his entry
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=0)
    skips = [e for e in out["_events"] if e.action == "skip"]
    assert [(e.coin, e.reason.split()[0]) for e in skips] == [("BTC", "mid")]

    venue.mids["BTC"] = 151.0                           # same reason, new numbers: quiet
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert [e for e in out["_events"] if e.action == "skip"] == []

    venue.fail_account(LEADER1)                         # a different reason: logged
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    skips = [e for e in out["_events"] if e.action == "skip"]
    assert [(e.leader, e.reason) for e in skips] == [(LEADER1, "leader read failed")]


# ── unified / portfolio margin: one shared pool, not one per dex ───────────

def test_unified_margin_is_one_pool_spent_across_dexes(engine_state, venue):
    """hl repeats the unified spot pool under every dex key. Opening on main
    must shrink the room on xyz too, or two copies on two dexes in one
    cycle would each think they had the whole pool."""
    # unified: equity is spot USDC (+uPnL), perp accountValue is not added
    venue.set_account(OUR, 10.0, spot_usdc=10.0, available={"": 1.0, "xyz": 1.0})
    venue.accounts[OUR]["abstraction"] = "unifiedAccount"
    venue.max_levs.update({"BTC": 20, "xyz:TSLA": 10})
    venue.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    venue.hold(LEADER2, "xyz:TSLA", 1.0, entry_px=100.0)
    s = cfg(leaders=[LEADER1, LEADER2], sizing_mode="fixed_margin", fixed_margin_usd=0.6,
            leverage_mode="max")
    out = run(venue, s, engine_state)
    assert out["opened"] == ["BTC"]                       # $0.60 margin of the $1 pool
    assert "xyz:TSLA" in out["skipped"]                   # only $0.40 left, not a fresh $1
    assert out["available_margin_usd"] == 1.0             # reported once, not summed per dex


def test_standard_account_keeps_per_dex_margin(engine_state, venue):
    venue.set_account(OUR, 10.0, available={"": 1.0, "xyz": 1.0})
    venue.max_levs.update({"BTC": 20, "xyz:TSLA": 20})
    venue.hold(LEADER1, "BTC", 1.0, entry_px=100.0)
    venue.hold(LEADER2, "xyz:TSLA", 1.0, entry_px=100.0)
    s = cfg(leaders=[LEADER1, LEADER2], sizing_mode="fixed_margin", fixed_margin_usd=0.6,
            leverage_mode="max")
    out = run(venue, s, engine_state)
    assert sorted(out["opened"]) == ["BTC", "xyz:TSLA"]
    assert out["available_margin_usd"] == 2.0
