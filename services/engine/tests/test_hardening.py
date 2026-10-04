"""Hardening tests: the worker loop (no overlap, no stacking, poll interval
re-read every cycle, single worker per data dir, SIGTERM), "our copy
vanished" without a leader move (liquidation), partial IOC fills, equity
under HL unified accounts, and the emergency close-all flag. <2s, no
network: FakeVenue + a fake clock only.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal

import pytest
from engine import core, public, sizing
from engine.events import read_events
from engine_fakes import LEADER1, OUR, FakeVenue
from test_core import cfg, run

from contracts.models import Settings

# ── worker loop ─────────────────────────────────────────────────────────────

class FakeTime:
    """Stands in for the `time` module inside engine.public: monotonic clock
    and sleep are fully simulated, so the loop's timing is asserted exactly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s
        self.slept += s

    def time(self) -> float:
        return 1_700_000_000.0 + self.now


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS", raising=False)
    return tmp_path


def _write_settings(data_dir, **kw) -> None:
    (data_dir / "settings.json").write_text(Settings(**kw).model_dump_json())


def test_cycles_never_overlap_never_stack_and_reread_poll_interval_each_cycle(data_dir, monkeypatch):
    clock = FakeTime()
    monkeypatch.setattr(public, "time", clock)
    _write_settings(data_dir, poll_interval_s=5)
    durations = [1.0, 20.0, 0.5, 0.5]       # cycle 2 is the slow first full dex scan
    starts, in_flight, max_in_flight = [], [0], [0]
    real_cycle = public.run_cycle

    def timed_cycle(venue, now_ms=None):
        i = len(starts)
        starts.append(clock.now)
        in_flight[0] += 1
        max_in_flight[0] = max(max_in_flight[0], in_flight[0])
        if i == 2:
            _write_settings(data_dir, poll_interval_s=2)   # edited between cycles
        clock.now += durations[i]
        try:
            return real_cycle(venue)
        finally:
            in_flight[0] -= 1

    monkeypatch.setattr(public, "run_cycle", timed_cycle)
    public.run_forever(FakeVenue(), max_cycles=4)

    # 0: 1s cycle, sleeps 4 -> 5. 5: 20s cycle overruns, next starts at once (25).
    # 25: settings now say 2s -> 0.5s cycle, sleeps 1.5 -> 27.
    assert starts == pytest.approx([0.0, 5.0, 25.0, 27.0])
    assert max_in_flight[0] == 1


def test_a_second_worker_on_the_same_data_dir_refuses_to_start(data_dir):
    with open(data_dir / public.LOCK_FILE, "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(public.EngineAlreadyRunning):
            public.run_forever(FakeVenue(), max_cycles=1)
    public.run_forever(FakeVenue(), max_cycles=1)       # released -> starts fine


def test_sigterm_mid_cycle_finishes_the_cycle_then_stops_without_sleeping(data_dir, monkeypatch):
    clock = FakeTime()
    monkeypatch.setattr(public, "time", clock)
    calls = []
    real_cycle = public.run_cycle

    def cycle(venue, now_ms=None):
        calls.append(1)
        os.kill(os.getpid(), signal.SIGTERM)
        return real_cycle(venue)

    monkeypatch.setattr(public, "run_cycle", cycle)
    public.run_forever(FakeVenue(), max_cycles=5)
    assert len(calls) == 1 and clock.slept == 0.0


def test_events_logged_before_a_mid_cycle_crash_are_kept(data_dir, monkeypatch):
    from contracts.models import EngineEvent

    def crashing(settings, venue, state, our_address, now_ms, log_event, stops=None):
        log_event(EngineEvent(ts_ms=now_ms, action="open", coin="BTC"))
        raise RuntimeError("boom after the order went through")

    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", OUR)     # no account = idle cycle, core never runs
    monkeypatch.setattr(core, "run_cycle", crashing)
    with pytest.raises(RuntimeError):
        public.run_cycle(FakeVenue(), now_ms=7)
    assert [(e.action, e.coin) for e in read_events(data_dir / "events.jsonl")] == [("open", "BTC")]


# ── our copy vanished while the leader sits still (liquidation) ─────────────

def _open_btc(engine_state, venue, **kw):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1], **kw), engine_state)
    assert out["opened"] == ["BTC"]
    return out


def test_liquidated_copy_is_confirmed_then_dropped_with_its_last_liq_px(engine_state, venue):
    _open_btc(engine_state, venue)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0, liquidation_px=91.5)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert [p.coin for p in out["positions"]] == ["BTC"]

    venue.hold(OUR, "BTC", 0.0)                       # HL liquidated us; he did not move
    events = []
    out = core.run_cycle(cfg(leaders=[LEADER1]), venue, engine_state, OUR, 2, events.append)
    assert out["positions"] == []                     # no zero-size ghost row in the UI
    assert len(engine_state.all_copies()) == 1        # one read is not proof
    assert not any(e.action == "skip" and e.coin == "BTC" for e in events)

    events = []
    out = core.run_cycle(cfg(leaders=[LEADER1]), venue, engine_state, OUR, 3, events.append)
    assert out["vanished"] == ["BTC"] and engine_state.all_copies() == []
    vanished = [e for e in events if e.coin == "BTC"]
    assert len(vanished) == 1 and vanished[0].action == "skip" and vanished[0].leader == LEADER1
    assert vanished[0].reason == ("our copy vanished (liquidated or closed outside copycat), "
                                  "last liq px 91.5")
    assert "BTC" in engine_state.get_leader(LEADER1).ignored   # no re-entry mid-position

    venue.hold(LEADER1, "BTC", 0.0)                   # he exits: nothing to do, ignore clears
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=4)
    assert not venue.closes and "BTC" not in engine_state.get_leader(LEADER1).ignored


def test_one_degraded_read_missing_our_copy_does_not_drop_it(engine_state, venue):
    _open_btc(engine_state, venue)
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)          # missing once
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)                          # back next read
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["vanished"] == [] and len(engine_state.all_copies()) == 1
    venue.hold(OUR, "BTC", 0.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=3)    # pending restarts
    assert out["vanished"] == [] and len(engine_state.all_copies()) == 1


def test_vanished_with_no_known_liq_px_says_unknown(engine_state, venue):
    _open_btc(engine_state, venue)
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    events = []
    core.run_cycle(cfg(leaders=[LEADER1]), venue, engine_state, OUR, 2, events.append)
    assert any(e.reason and e.reason.endswith("last liq px unknown") for e in events)


def test_a_leader_move_on_a_missing_copy_trades_nothing_until_confirmed(engine_state, venue):
    _open_btc(engine_state, venue)
    venue.hold(LEADER1, "BTC", 500.0, entry_px=100.0)                   # he reduces
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert len(venue.orders) == 1 and not venue.closes
    assert out["skipped"]["BTC"].startswith("our copy is missing")


# ── partial IOC fills ───────────────────────────────────────────────────────

def test_partial_open_logs_the_filled_notional_and_the_add_uses_our_real_size(engine_state, venue):
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.fill_frac["BTC"] = 0.5
    events = []
    s = cfg(leaders=[LEADER1], sizing_mode="fixed_notional", fixed_notional_usd=40.0)
    core.run_cycle(s, venue, engine_state, OUR, 0, events.append)
    opened = [e for e in events if e.action == "open"][0]
    assert venue.orders == [("BTC", True, 0.4, False)]
    assert opened.notional_usd == 20.0 and "partial fill 0.2 of 0.4" in opened.reason

    del venue.fill_frac["BTC"]
    venue.hold(OUR, "BTC", 0.2, entry_px=100.0)       # what actually filled
    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)  # he doubles
    out = run(venue, s, engine_state, now_ms=1)
    assert out["added"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", True, 0.2, False)   # doubles 0.2, not the assumed 0.4


def test_partial_reduce_retries_exactly_the_unfilled_part(engine_state, venue):
    _open_btc(engine_state, venue)
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 250.0)                 # he takes 75% off
    venue.fill_frac["BTC"] = 0.5
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert venue.orders[-1] == ("BTC", False, 1.5, True)   # only 0.75 fills
    assert out["skipped"]["BTC"].startswith("reduce partially filled")
    assert engine_state.get_leader(LEADER1).last_positions["BTC"] == pytest.approx(625.0)

    del venue.fill_frac["BTC"]
    venue.hold(OUR, "BTC", 1.25, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["reduced"] == ["BTC"]
    assert venue.orders[-1] == ("BTC", False, 0.75, True)  # 2.0 * 0.25 = 0.5 left, as intended
    assert engine_state.get_leader(LEADER1).last_positions["BTC"] == 250.0
    run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=3)
    assert len(venue.orders) == 3                     # settled, no further reduce


def test_partial_close_keeps_the_copy_and_retries(engine_state, venue):
    _open_btc(engine_state, venue)
    venue.hold(OUR, "BTC", 2.0, entry_px=100.0)
    venue.hold(LEADER1, "BTC", 0.0)
    venue.close_filled["BTC"] = 1.2
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=1)
    assert out["closed"] == [] and len(engine_state.all_copies()) == 1
    assert out["skipped"]["BTC"].startswith("close partially filled (1.2 of 2)")

    del venue.close_filled["BTC"]
    venue.hold(OUR, "BTC", 0.8, entry_px=100.0)
    out = run(venue, cfg(leaders=[LEADER1]), engine_state, now_ms=2)
    assert out["closed"] == ["BTC"] and engine_state.all_copies() == []


# ── equity under HL account abstraction modes ───────────────────────────────

def _acct(abstraction=None, upnl=(0.0,)):
    a = {"equity_perp_usd": 441_358.0, "spot_usdc": 525_231.0, "positions": {},
         "available": {}, "raw_positions": {f"C{i}": {"unrealizedPnl": str(u)} for i, u in enumerate(upnl)}}
    if abstraction:
        a["abstraction"] = abstraction
    return a


def test_unified_and_portfolio_margin_equity_is_spot_usdc_plus_upnl_not_perp_plus_spot():
    # numbers from a real USDC-only unified wallet, 2026-10-03 (HL portfolio value: $534,051)
    for mode in ("unifiedAccount", "portfolioMargin"):
        assert sizing.account_equity(_acct(mode, (1_653.5,))) == pytest.approx(526_884.5)


def test_standard_and_unknown_modes_keep_perp_plus_spot():
    for mode in (None, "default", "disabled", "dexAbstraction"):
        assert sizing.account_equity(_acct(mode, (1_653.5,))) == pytest.approx(966_589.0)


def test_unified_leader_equity_drives_proportional_size(engine_state, venue):
    venue.set_account(OUR, 1000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0, equity_perp_usd=1_000_000.0,
               spot_usdc=500_000.0)
    venue.accounts[LEADER1]["abstraction"] = "unifiedAccount"
    out = run(venue, cfg(leaders=[LEADER1]), engine_state)
    # his equity = spot 500k + uPnL 0 (not 1.5M): 100k/500k * 500 allocation = $100
    assert out["opened"] == ["BTC"] and venue.orders == [("BTC", True, 1.0, False)]


# ── emergency close-all (data/close_all.flag) ───────────────────────────────

@pytest.fixture
def live_dir(data_dir, monkeypatch):
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", OUR)
    _write_settings(data_dir, **json.loads(cfg(leaders=[LEADER1]).model_dump_json()))
    return data_dir


def test_close_all_flattens_every_copy_clears_the_flag_and_blocks_reentry(live_dir):
    venue = FakeVenue()
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)
    public.run_cycle(venue, now_ms=1)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    venue.hold(OUR, "ETH", 0.5, entry_px=100.0)
    venue.hold(OUR, "SOL", 3.0, entry_px=100.0)       # not ours: must never be touched
    (live_dir / public.CLOSE_ALL_FLAG).write_text("{}")

    summary = public.run_cycle(venue, now_ms=2)
    assert sorted(venue.closes) == ["BTC", "ETH"]
    assert summary["close_all"]["remaining"] == 0
    assert not (live_dir / public.CLOSE_ALL_FLAG).exists()
    evs = read_events(live_dir / "events.jsonl", limit=50)
    assert {(e.action, e.coin) for e in evs if e.reason == "close-all"} == {("close", "BTC"),
                                                                           ("close", "ETH")}
    assert any(e.action == "halt" and e.reason.startswith("close-all complete") for e in evs)

    venue.hold(OUR, "BTC", 0.0)
    venue.hold(OUR, "ETH", 0.0)
    venue.hold(LEADER1, "BTC", 2000.0, entry_px=100.0)   # he adds; we are out, stay out
    n_orders = len(venue.orders)
    public.run_cycle(venue, now_ms=3)
    assert len(venue.orders) == n_orders


def test_close_all_keeps_the_flag_while_a_close_fails_and_forces_entries_off(live_dir):
    venue = FakeVenue()
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    public.run_cycle(venue, now_ms=1)
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    (live_dir / public.CLOSE_ALL_FLAG).write_text("{}")
    venue.fail_close = True
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)  # would open if entries were on
    summary = public.run_cycle(venue, now_ms=2)
    assert summary["close_all"]["failed"].keys() == {"BTC"}
    assert (live_dir / public.CLOSE_ALL_FLAG).exists()
    assert summary["opened"] == []

    venue.fail_close = False
    summary = public.run_cycle(venue, now_ms=3)
    assert summary["close_all"]["closed"] == ["BTC"]
    assert not (live_dir / public.CLOSE_ALL_FLAG).exists()


def test_close_all_closes_real_copies_even_in_dry_run_and_clears_the_shadow(live_dir):
    venue = FakeVenue()
    venue.set_account(OUR, 1_000_000.0)
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    public.run_cycle(venue, now_ms=1)                   # real copy
    venue.hold(OUR, "BTC", 0.5, entry_px=100.0)
    _write_settings(live_dir, **json.loads(cfg(leaders=[LEADER1], dry_run=True).model_dump_json()))
    venue.hold(LEADER1, "ETH", 1000.0, entry_px=100.0)
    public.run_cycle(venue, now_ms=2)                   # shadow copy of ETH
    (live_dir / public.CLOSE_ALL_FLAG).write_text("{}")
    public.run_cycle(venue, now_ms=3)
    assert venue.closes == ["BTC"]
    from engine.state import EngineState
    with EngineState(public._db_path(OUR)) as st:   # per-account state db
        assert st.all_copies() == [] and st.all_dry_copies() == []
