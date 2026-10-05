"""Contract v8 in the engine: trade_direction counter, coin allow/block lists,
pause, skip events tagged with their leader, archived orphans. Hand numbers:

proportional sizing, our equity $10,000, sleeve 0.5, one leader -> $5,000 sleeve.
His equity $1,000,000. A position of 1000 BTC @ 100 is $100,000 of his notional:
100,000 / 1,000,000 x 5,000 = $500 -> 5.0 BTC at mid 100.
"""
from __future__ import annotations

import sqlite3

from engine import core, sizing
from engine.state import EngineState
from engine_fakes import LEADER1, LEADER2, OUR

from contracts.models import LeaderOverride, Settings

EQ = 10_000.0


def cfg(**kw) -> Settings:
    base = dict(enabled=True, dry_run=False, leaders=[LEADER1], sleeve_frac=0.5,
                max_position_leverage=50, leverage_mode="max", margin_mode="isolated",
                max_worse_entry_pct=10.0, min_order_bump=True, sizing_mode="proportional",
                size_multiplier=1.0)
    base.update(kw)
    return Settings(**base)


def run(venue, settings, state, now_ms=0):
    events = []
    out = core.run_cycle(settings, venue, state, OUR, now_ms, events.append)
    out["_events"] = events
    return out


def ours(venue, coin, szi, entry=100.0):
    """Our account after the fill (FakeVenue.market does not move positions)."""
    venue.hold(OUR, coin, szi, entry_px=entry, equity_perp_usd=EQ, available={"": EQ, "xyz": EQ})


def setup(venue):
    venue.set_account(OUR, EQ, available={"": EQ, "xyz": EQ})


# ── sizing helpers ───────────────────────────────────────────────────────────

def test_our_is_long_copy_follows_his_side_counter_inverts_it():
    assert sizing.our_is_long(5.0, "copy") is True
    assert sizing.our_is_long(-5.0, "copy") is False
    assert sizing.our_is_long(5.0, "counter") is False
    assert sizing.our_is_long(-5.0, "counter") is True


def test_counter_worse_entry_uses_our_side_against_his_entry():
    # he is long @100, we counter-short: ok while mid >= 100 x (1 - 0.10) = 90
    assert sizing.worse_entry_ok("short", 90.0, 100.0, 10.0)
    assert not sizing.worse_entry_ok("short", 89.9, 100.0, 10.0)
    assert sizing.worse_entry_ok("short", 130.0, 100.0, 10.0)     # higher is better for a short
    # he is short @100, we counter-long: ok while mid <= 110
    assert sizing.worse_entry_ok("long", 110.0, 100.0, 10.0)
    assert not sizing.worse_entry_ok("long", 110.1, 100.0, 10.0)
    assert sizing.worse_entry_ok("long", 70.0, 100.0, 10.0)


def test_coin_allowed_is_case_insensitive_and_keeps_the_hip3_dex_form():
    s = cfg(coin_allowlist=["btc", "XYZ:tsla"])
    assert sizing.coin_allowed(s, "BTC")
    assert sizing.coin_allowed(s, "xyz:TSLA")
    assert not sizing.coin_allowed(s, "TSLA")          # plain TSLA is not the xyz dex one
    assert not sizing.coin_allowed(s, "ETH")
    s = cfg(coin_blocklist=["Eth"])
    assert not sizing.coin_allowed(s, "ETH")
    assert sizing.coin_allowed(s, "BTC")
    assert sizing.coin_allowed(cfg(), "anything")      # empty lists filter nothing


# ── counter: open / add / reduce / close / flip ─────────────────────────────

def test_counter_open_add_reduce_close(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)            # he goes long
    out = run(venue, s, engine_state, 0)
    assert out["opened"] == ["BTC"]
    assert venue.orders == [("BTC", False, 5.0, False)]          # we SELL 5.0: a short
    assert engine_state.get_copy("BTC").direction == "counter"
    ev = [e for e in out["_events"] if e.action == "open"][0]
    assert ev.side == "short" and "counter" in (ev.reason or "")

    ours(venue, "BTC", -5.0)
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)            # he adds 500 BTC = $50,000
    out = run(venue, s, engine_state, 1)
    assert out["added"] == ["BTC"]
    # 50,000 / 1,000,000 x 5,000 = $250 -> 2.5, on OUR side (sell)
    assert venue.orders[-1] == ("BTC", False, 2.5, False)

    ours(venue, "BTC", -7.5)
    venue.hold(LEADER1, "BTC", 750.0, entry_px=100.0)             # he takes half off
    out = run(venue, s, engine_state, 2)
    assert out["reduced"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 3.75, True)         # buy back half, reduce-only

    ours(venue, "BTC", -3.75)
    venue.hold(LEADER1, "BTC", 0.0)                                # he closes
    out = run(venue, s, engine_state, 3)
    assert out["closed"] == ["BTC"] and venue.closes == ["BTC"]
    assert engine_state.get_copy("BTC") is None


def test_counter_short_leader_means_we_go_long(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "ETH", -1000.0, entry_px=100.0)
    out = run(venue, cfg(trade_direction="counter"), engine_state)
    assert out["opened"] == ["ETH"]
    assert venue.orders == [("ETH", True, 5.0, False)]


def test_counter_flip_closes_then_opens_the_opposite_of_his_new_side(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, s, engine_state, 0)
    ours(venue, "BTC", -5.0)
    venue.hold(LEADER1, "BTC", -1000.0, entry_px=100.0)           # long -> short in one read
    out = run(venue, s, engine_state, 1)
    assert venue.closes == ["BTC"]
    assert out["opened"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 5.0, False)         # he is short now: we go long
    assert engine_state.get_copy("BTC").direction == "counter"


def test_counter_worse_entry_blocks_a_short_sold_too_low_but_not_too_high(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)            # he is long @100
    venue.mids["BTC"] = 85.0                                       # we would short 15% under his entry
    out = run(venue, s, engine_state, 0)
    assert "worse than entry" in out["skipped"]["BTC"] and not venue.orders
    venue.mids["BTC"] = 115.0                                      # a copy-long would be blocked here
    out = run(venue, s, engine_state, 1)
    assert out["opened"] == ["BTC"]
    assert venue.orders[-1][:2] == ("BTC", False)


def test_counter_worse_entry_blocks_a_long_bought_too_high_but_not_too_low(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", -1000.0, entry_px=100.0)           # he is short @100
    venue.mids["BTC"] = 115.0
    out = run(venue, s, engine_state, 0)
    assert "worse than entry" in out["skipped"]["BTC"] and not venue.orders
    venue.mids["BTC"] = 85.0
    out = run(venue, s, engine_state, 1)
    assert out["opened"] == ["BTC"]
    assert venue.orders[-1][:2] == ("BTC", True)


def test_counter_liquidity_cap_reads_the_book_on_our_order_side(engine_state, venue):
    setup(venue)
    sides = []
    orig = venue.depth_usd

    def depth(coin, is_buy, pct):
        sides.append(is_buy)
        return orig(coin, is_buy, pct)
    venue.depth_usd = depth
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(trade_direction="counter"), engine_state)
    assert sides == [False]                                        # we sell, so the bid side


def test_direction_change_mid_copy_keeps_the_open_copys_side(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(trade_direction="copy"), engine_state, 0)
    assert venue.orders == [("BTC", True, 5.0, False)]           # opened as a copy: long
    ours(venue, "BTC", 5.0)

    s = cfg(trade_direction="counter")                             # user switches the wallet
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)
    out = run(venue, s, engine_state, 1)
    assert out["added"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 2.5, False)         # still adds LONG
    assert engine_state.get_copy("BTC").direction == "copy"

    ours(venue, "BTC", 7.5)
    venue.hold(LEADER1, "BTC", -1000.0, entry_px=100.0)           # he flips: the new open is counter
    out = run(venue, s, engine_state, 2)
    assert venue.closes == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 5.0, False)         # he is short -> we are long
    assert engine_state.get_copy("BTC").direction == "counter"


def test_add_skipped_when_our_real_side_does_not_match_the_copys_direction(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, s, engine_state, 0)
    ours(venue, "BTC", 5.0)                                        # someone flipped it long by hand
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)
    out = run(venue, s, engine_state, 1)
    assert "add skipped" in out["skipped"]["BTC"]
    assert len(venue.orders) == 1


def test_stranded_counter_copy_is_still_closed(engine_state, venue):
    setup(venue)
    s = cfg(trade_direction="counter")
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, s, engine_state, 0)
    ours(venue, "BTC", -5.0)
    ls = engine_state.get_leader(LEADER1)
    ls.last_positions = {}                                         # his last-seen size lost
    engine_state.put_leader(ls)
    venue.hold(LEADER1, "BTC", 0.0)
    out = run(venue, s, engine_state, 1)
    assert out["closed"] == ["BTC"]


def test_dry_run_counter_records_the_shadow_direction(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(trade_direction="counter", dry_run=True), engine_state)
    intent = [e for e in out["_events"] if e.action == "intent"][0]
    assert intent.side == "short"
    dc = engine_state.get_dry_copy("BTC")
    assert dc.direction == "counter" and dc.size == -5.0


def test_per_wallet_override_direction(engine_state, venue):
    setup(venue)
    s = cfg(leaders=[LEADER1, LEADER2],
            leader_overrides={LEADER2: LeaderOverride(trade_direction="counter")})
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER2, "ETH", 1000.0, entry_px=100.0)
    run(venue, s, engine_state)
    sides = {o[0]: o[1] for o in venue.orders}
    assert sides == {"BTC": True, "ETH": False}


# ── coin filters ─────────────────────────────────────────────────────────────

def test_allowlist_skips_other_coins_case_insensitively(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)
    out = run(venue, cfg(coin_allowlist=["eth"]), engine_state)
    assert out["opened"] == ["ETH"]
    assert out["skipped"]["BTC"] == "filtered: BTC"
    skip = [e for e in out["_events"] if e.action == "skip" and e.coin == "BTC"][0]
    assert skip.leader == LEADER1                       # skip events carry their wallet


def test_blocklist_hip3_coin_keeps_its_dex_form(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "xyz:TSLA", 1000.0, entry_px=100.0)
    venue.hold(LEADER1, "TSLA", 1000.0, entry_px=100.0)
    out = run(venue, cfg(coin_blocklist=["XYZ:tsla"]), engine_state)
    assert out["opened"] == ["TSLA"]
    assert out["skipped"]["xyz:TSLA"] == "filtered: xyz:TSLA"


def test_filtered_open_stays_ignored_until_he_goes_flat(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(coin_blocklist=["BTC"]), engine_state, 0)
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 1)                 # list cleared: no midway entry
    assert not venue.orders
    venue.hold(LEADER1, "BTC", 0.0)
    run(venue, cfg(), engine_state, 2)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(), engine_state, 3)
    assert out["opened"] == ["BTC"]


def test_exits_are_never_filtered_but_adds_are(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 0)
    ours(venue, "BTC", 5.0)
    blocked = cfg(coin_blocklist=["BTC"])
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)
    out = run(venue, blocked, engine_state, 1)
    assert out["skipped"]["BTC"] == "filtered: BTC" and len(venue.orders) == 1
    venue.hold(LEADER1, "BTC", 750.0, entry_px=100.0)             # 1500 -> 750: half off
    out = run(venue, blocked, engine_state, 2)
    assert out["reduced"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", False, 2.5, True)
    ours(venue, "BTC", 2.5)
    venue.hold(LEADER1, "BTC", 0.0)
    out = run(venue, cfg(coin_allowlist=["ETH"]), engine_state, 3)
    assert out["closed"] == ["BTC"]


def test_global_list_applies_unless_the_wallet_sets_its_own(engine_state, venue):
    setup(venue)
    s = cfg(leaders=[LEADER1, LEADER2], coin_blocklist=["SOL"],
            leader_overrides={LEADER2: LeaderOverride(coin_blocklist=[])})
    venue.hold(LEADER1, "SOL", 1000.0, entry_px=100.0)
    venue.hold(LEADER2, "SOL", 1000.0, entry_px=100.0)
    out = run(venue, s, engine_state)
    assert out["opened"] == ["SOL"]
    assert engine_state.get_copy("SOL").leader == LEADER2


# ── pause ────────────────────────────────────────────────────────────────────

def test_pause_blocks_opens_and_adds_but_exits_still_mirror(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    run(venue, cfg(), engine_state, 0)
    ours(venue, "BTC", 5.0)
    paused = cfg(leader_overrides={LEADER1: LeaderOverride(paused=True)})
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)            # new open
    venue.hold(LEADER1, "BTC", 1500.0, entry_px=100.0)            # add
    out = run(venue, paused, engine_state, 1)
    assert out["skipped"]["ETH"] == "paused" and out["skipped"]["BTC"] == "paused"
    assert len(venue.orders) == 1
    venue.hold(LEADER1, "BTC", 0.0)                                # exit while paused
    out = run(venue, paused, engine_state, 2)
    assert out["closed"] == ["BTC"]


def test_book_wide_pause_pauses_every_wallet(engine_state, venue):
    setup(venue)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(paused=True), engine_state)
    assert out["skipped"]["BTC"] == "paused" and not venue.orders


def test_catch_up_waits_while_paused(engine_state, venue):
    setup(venue)
    venue.depth["BTC"] = 200.0                                     # $500 order -> $200 now, $300 later
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(), engine_state, 0)
    assert out["split"] == ["BTC"]
    ours(venue, "BTC", 2.0)
    out = run(venue, cfg(leader_overrides={LEADER1: LeaderOverride(paused=True)}), engine_state, 1)
    assert out["skipped"]["BTC"] == "catch-up paused: paused"
    assert len(venue.orders) == 1
    assert engine_state.get_kv("catch_up")["BTC"]["remaining_usd"] == 300.0


# ── archived orphans ─────────────────────────────────────────────────────────

def test_archived_orphan_without_copies_is_not_read_any_more(engine_state, venue):
    setup(venue)
    venue.hold(LEADER2, "ETH", 0.0)
    run(venue, cfg(leaders=[LEADER1, LEADER2]), engine_state, 0)   # LEADER2 now has a row
    venue.fail_account(LEADER2)
    out = run(venue, cfg(), engine_state, 1)                        # orphan: still read
    assert out["skipped"].get(f"leader:{LEADER2}") == "leader read failed"
    engine_state.archive_ledger(LEADER2, 5)
    out = run(venue, cfg(), engine_state, 2)
    assert f"leader:{LEADER2}" not in out["skipped"]
    assert out["leaders_total"] == 1


def test_archived_orphan_with_a_copy_keeps_mirroring_exits(engine_state, venue):
    setup(venue)
    venue.hold(LEADER2, "ETH", 1000.0, entry_px=100.0)
    run(venue, cfg(leaders=[LEADER2]), engine_state, 0)
    ours(venue, "ETH", 5.0)
    engine_state.archive_ledger(LEADER2, 5)                         # must not strand the copy
    venue.hold(LEADER2, "ETH", 0.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, 1)
    assert out["closed"] == ["ETH"]


def test_fresh_investment_unarchives_the_ledger(engine_state):
    engine_state.sync_ledger(LEADER1, 100, {}, 100)
    engine_state.archive_ledger(LEADER1, 200)
    assert engine_state.get_ledger(LEADER1)["archived_ms"] == 200
    engine_state.sync_ledger(LEADER1, 100, {}, 300)                # same investment: stays archived
    assert engine_state.get_ledger(LEADER1)["archived_ms"] == 200
    engine_state.sync_ledger(LEADER1, 400, {}, 400)
    assert engine_state.get_ledger(LEADER1)["archived_ms"] is None


# ── migration ────────────────────────────────────────────────────────────────

def test_pre_v8_db_gets_direction_copy_and_archived_ms(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE copies (coin TEXT PRIMARY KEY, leader TEXT NOT NULL, opened_ms INTEGER NOT NULL,
            leverage INTEGER NOT NULL, is_cross INTEGER NOT NULL, sizing_mode TEXT NOT NULL,
            pending_cloid TEXT);
        CREATE TABLE dry_copies (coin TEXT PRIMARY KEY, leader TEXT NOT NULL, opened_ms INTEGER NOT NULL,
            leverage INTEGER NOT NULL, is_cross INTEGER NOT NULL, sizing_mode TEXT NOT NULL,
            size REAL NOT NULL);
        CREATE TABLE ledger (leader TEXT PRIMARY KEY, invested_ms INTEGER,
            realized_pnl_usd REAL NOT NULL DEFAULT 0, fees_usd REAL NOT NULL DEFAULT 0,
            terms TEXT NOT NULL DEFAULT '{}', updated_ms INTEGER);
        INSERT INTO copies VALUES ('BTC', '0xabc', 1, 10, 0, 'proportional', NULL);
        INSERT INTO ledger VALUES ('0xabc', 1, 2.5, 0.1, '{}', 1);
    """)
    conn.commit()
    conn.close()
    with EngineState(path) as st:
        assert st.get_copy("BTC").direction == "copy"
        assert st.get_ledger("0xabc")["archived_ms"] is None
