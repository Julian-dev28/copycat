"""Scout refresh: switchover, single-slot busy, stage budget, settings
changes (stale_settings), the scheduler tick and on-demand requests."""
from __future__ import annotations

import threading
import time

import pytest
from discovery.scout import public, stats, store
from discovery.scout import refresh as R
from test_scout_helpers import addr, portfolio, trips
from test_scout_world import BOARD, DAY, EQUITY, NOW, A, D, G, q, settings, world

from contracts.models import ScoutStatus, TraderProfile


@pytest.fixture
def w(tmp_path, monkeypatch):
    return world(tmp_path, monkeypatch)


def test_old_rows_serve_while_refresh_runs(w):
    v, db = w["venue"], w["db"]
    before = public.scout_page(q())
    v.block = threading.Event()
    v.portfolio_calls.clear()
    errs = []
    th = threading.Thread(target=lambda: _safe(errs, lambda: R.run_refresh(v, settings(), EQUITY, db_path=db)))
    th.start()
    deadline = time.time() + 5
    while not v.portfolio_calls and time.time() < deadline:
        time.sleep(0.01)
    during = public.scout_page(q())
    st = public.scout_status()
    assert during.refresh_id == before.refresh_id and during.total == 6
    assert st.state == "running" and st.stage == "stats"
    with pytest.raises(public.ScoutBusy):
        public.scout_refresh()
    with pytest.raises(R.ScoutBusy):
        R.run_refresh(v, settings(), EQUITY, db_path=db)
    v.block.set()
    th.join(5)
    assert not errs
    after = public.scout_page(q())
    assert after.refresh_id != before.refresh_id and after.total == 6
    assert public.scout_status().state == "idle"


def _safe(errs, fn):
    try:
        fn()
    except Exception as e:      # surfaced by the assert in the test
        errs.append(e)


def test_unswitched_rows_are_invisible_and_retention_keeps_3(w):
    conn = store.connect(w["db"])
    ptr = store.pointer(conn)
    store.write_rows(conn, [{"refresh_id": "half", "settings_hash": ptr["settings_hash"], "address": addr(99),
                             "row_json": "{}"}])
    assert public.scout_page(q()).refresh_id == ptr["refresh_id"] and public.scout_page(q()).total == 6
    for _ in range(4):
        R.run_refresh(w["venue"], settings(), EQUITY, R.RefreshOptions(stages=("A",)), db_path=w["db"])
    ids = {r[0] for r in conn.execute("SELECT DISTINCT refresh_id FROM scout_rows").fetchall()}
    assert len(ids) == 3 and "half" not in ids


def test_stage_b_budget_orders_book_first_and_defers(tmp_path):
    from test_scout_world import build_venue
    v = build_venue()
    conn = store.connect(tmp_path / "b.db")
    addrs = sorted(BOARD)
    est = stats.estimate_weight(False)
    budget = stats.Budget(max_weight=est + 1, max_s=60)     # room for exactly one cold wallet
    res = stats.run_stage_b(conn, v, addrs, NOW, budget, book=[G])
    assert res.done == [G] and len(res.deferred) == 5
    assert budget.spent <= budget.max_weight
    # next pass: never-built wallets come before the ones just built
    res2 = stats.run_stage_b(conn, v, addrs, NOW, stats.Budget(1e9, 60), book=[])
    assert res2.done[:5] == res.deferred and res2.done[5] == G


def test_stage_b_wall_clock_budget():
    t = [0.0]
    b = stats.Budget(max_weight=1e9, max_s=10, clock=lambda: t[0])
    assert b.allows(1)
    t[0] = 10
    assert not b.allows(1)


def test_failed_wallet_keeps_old_stats_and_sits_out(w):
    conn = store.connect(w["db"])
    v = w["venue"]
    v.set_portfolio(A, None)
    old = store.stats_row(conn, A)["updated_ms"]
    for _ in range(2):
        stats.run_stage_b(conn, v, [A], NOW, stats.Budget(1e9, 60))
    row = store.stats_row(conn, A)
    assert row["updated_ms"] == old and row["fail_count"] == 2 and row["skip_until_ms"] > NOW
    assert stats.order_wallets([A], store.stats_index(conn), [], [], NOW) == []


def test_settings_change_serves_old_board_flagged_stale_until_rescored(w):
    v, db = w["venue"], w["db"]
    old = public.scout_page(q())
    new = settings(fixed_margin_usd=2.0)
    conn = store.connect(db)
    store.meta_set(conn, {"wanted_hash": R.settings_hash(new, EQUITY)})   # what serve writes each tick
    p = public.scout_page(q())
    assert p.stale_settings and p.settings_hash == old.settings_hash
    store.meta_set(conn, {"last_a_ms": R.now_ms(), "last_b_ms": R.now_ms()})
    assert R.plan(conn, R.settings_hash(new, EQUITY), R.now_ms()).stages == ["C"]
    R.tick(v, new, EQUITY, db_path=db)
    p2 = public.scout_page(q())
    assert not p2.stale_settings and p2.settings_hash == R.settings_hash(new, EQUITY)
    assert p2.rows[0].score.sim_fees_usd > 0


def test_settings_hash_ignores_book_and_switches():
    assert R.settings_hash(settings(), 1000) == R.settings_hash(settings(leaders=[], enabled=True), 1000)
    assert R.settings_hash(settings(), 1000) != R.settings_hash(settings(), 2000)
    assert R.settings_hash(settings(), 1000) != R.settings_hash(settings(fixed_margin_usd=3), 1000)


def test_refresh_request_is_picked_up_by_tick(w):
    conn = store.connect(w["db"])
    st = public.scout_refresh()
    assert st.error and "not running" in st.error          # no scheduler heartbeat yet
    with pytest.raises(public.ScoutBusy):
        public.scout_refresh()                               # already queued
    before = public.scout_page(q()).refresh_id
    R.tick(w["venue"], settings(), EQUITY, db_path=w["db"])
    assert store.meta_get(conn, "refresh_requested") is None
    assert public.scout_page(q()).refresh_id != before and R.scheduler_alive(conn)


def test_profile_unknown_wallet_is_queued_then_built_by_serve(w):
    v, db = w["venue"], w["db"]
    x = addr(42)
    assert public.scout_profile("not-an-address") is None
    out = public.scout_profile(x.upper().replace("0X", "0x"))
    assert isinstance(out, ScoutStatus) and out.state == "running"
    v.set_portfolio(x, portfolio([0, 10, 20, 30] * 3))
    v.set_fills(x, trips("BTC", 4, NOW - 9 * DAY))
    v.set_account_state(x, {"equity_perp_usd": 3000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})
    R.tick(v, settings(), EQUITY, db_path=db)
    prof = public.scout_profile(x)
    assert isinstance(prof, TraderProfile) and prof.row.address == x and prof.sim_curve
    assert x not in {r.address for r in public.scout_page(q()).rows}     # on-demand files stay off the board


def test_an_on_demand_request_is_built_exactly_once(w, monkeypatch):
    """The top-level request service runs a mini refresh per wallet; that refresh beats,
    and the beat used to drain the queue again while the same wallet was still in it,
    building every on-demand wallet twice (live: "built in 3s mid-refresh", "built in 6s")."""
    v, db = w["venue"], w["db"]
    x = addr(44)
    v.set_portfolio(x, portfolio([0, 10, 20, 30] * 3))
    v.set_fills(x, trips("BTC", 4, NOW - 9 * DAY))
    v.set_account_state(x, {"equity_perp_usd": 3000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})
    assert isinstance(public.scout_profile(x), ScoutStatus)       # queued
    built = []
    orig = v.portfolio

    def counting(user):
        if user == x:
            built.append(user)
        return orig(user)

    monkeypatch.setattr(v, "portfolio", counting)
    R.tick(v, settings(), EQUITY, db_path=db)
    assert built == [x], built
    assert store.request_row(store.connect(db), x) is None
    assert isinstance(public.scout_profile(x), TraderProfile)


def test_scheduler_start_frees_the_slot_a_killed_process_left_running(w):
    """A scout restart mid-refresh left a `running` row with a fresh heartbeat; the slot
    stayed taken for REFRESH_STALE_S and every tick did nothing for 15 minutes."""
    conn = store.connect(w["db"])
    assert store.try_begin_refresh(conn, "dead-process", R.now_ms(), "scheduled") is None
    assert R.on_scheduler_start(conn) == 1
    row = store.latest_refresh(conn)
    assert row["state"] == "failed" and row["error"] == "scout restarted"
    assert R.on_scheduler_start(conn) == 0                           # idempotent
    store.meta_set(conn, {"last_a_ms": 0, "last_b_ms": 0})
    before = public.scout_page(q()).refresh_id
    R.tick(w["venue"], settings(), EQUITY, db_path=w["db"])          # the slot is free: a refresh runs now
    assert public.scout_page(q()).refresh_id != before


def test_profile_request_that_keeps_failing_becomes_404(w):
    x = addr(43)                                            # the venue has no data for it
    assert isinstance(public.scout_profile(x), ScoutStatus)
    for _ in range(R.MAX_REQUEST_ATTEMPTS):
        R.tick(w["venue"], settings(), EQUITY, db_path=w["db"])
    assert public.scout_profile(x) is None


def test_departure_recorded_when_a_wallet_leaves_the_universe(w):
    """user_consensus P1 #7: a wallet that falls out of the ranked universe
    (not just one that liquidates) leaves a visible trail, classified by
    whether its last known stats showed a real liquidation."""
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    assert store.departures_summary(conn, 0) == {"departed": 0, "departed_liquidated": 0}
    v.set_leaderboard([row for row in v._leaderboard if row["ethAddress"] != D])   # D drops out
    R.run_refresh(v, settings(), EQUITY, db_path=db)
    summary = store.departures_summary(conn, 0)
    assert summary == {"departed": 1, "departed_liquidated": 0}     # D had no real liquidation
    assert D not in {u["address"] for u in store.universe(conn)}
    # idempotent: a second A-only refresh with the same (D-less) leaderboard records nothing new
    R.run_refresh(v, settings(), EQUITY, db_path=db, opts=R.RefreshOptions(stages=("A",)))
    assert store.departures_summary(conn, 0) == {"departed": 1, "departed_liquidated": 0}


def test_connect_adds_a_new_table_to_a_database_that_predates_it(tmp_path):
    """Regression: store.connect() used to gate the whole schema script on
    whether `scout_requests` existed, so a real, already-running
    data/discovery.db (every older scout table present, scout_departures
    added later) never got the new table and scout_presets() 500'd with
    "no such table: scout_departures" (caught live against a copy of real
    Scout data). The sentinel must track the NEWEST table in SCHEMA."""
    import sqlite3
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE scout_requests (address TEXT PRIMARY KEY)")   # the old sentinel, alone
    conn.commit()
    conn.close()

    conn2 = store.connect(db)
    assert conn2.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scout_departures'"
    ).fetchone() is not None
    assert store.departures_summary(conn2, 0) == {"departed": 0, "departed_liquidated": 0}   # no longer 500s


def test_scheduler_stays_alive_during_a_long_refresh(w, monkeypatch):
    """Health (`scout_build().alive`) and the queued status read
    `scheduler_heartbeat_ms`. The tick wrote it only before and after the
    stages, so any refresh longer than SCHEDULER_ALIVE_S (90s; a full ABC
    takes 20 to 45 minutes live) reported scout dead, "scout serve is not
    running; the build is queued", for its whole run. Every progress step
    now beats the scheduler heartbeat, but only when the scheduler runs the
    refresh: a CLI refresh must not fake a live scheduler."""
    v, db = w["venue"], w["db"]
    conn = store.connect(db)
    clock = {"t": R.now_ms()}
    monkeypatch.setattr(R, "now_ms", lambda: clock["t"])
    seen = []
    orig = v.portfolio

    def slow_portfolio(user):
        clock["t"] += 60_000                       # each trader's stats take a minute
        seen.append(R.scheduler_alive(conn, clock["t"]))
        return orig(user)

    monkeypatch.setattr(v, "portfolio", slow_portfolio)
    store.meta_set(conn, {"last_a_ms": 0, "last_b_ms": 0})      # stats due: the tick runs ABC
    R.tick(v, settings(), EQUITY, db_path=db)
    assert len(seen) >= 3, seen
    assert all(seen), seen                         # before the fix: [True, False, False, ...]

    # control: the same refresh outside the scheduler leaves a stale heartbeat stale
    store.meta_set(conn, {"scheduler_heartbeat_ms": clock["t"] - 10 * 60_000})
    seen.clear()
    R.run_refresh(v, settings(), EQUITY, db_path=db)
    assert seen and not any(seen), seen


# ── ETA honesty gate (indexing tightening: "eta 394m02s" from 7/301) ────────

def test_eta_hidden_below_both_thresholds_then_shown():
    assert R.eta_s(0, 301, 10.0) is None                 # no progress at all
    assert R.eta_s(7, 301, 60.0) is None                 # the exact regression: 7/301, 2.3%
    assert R.eta_s(9, 301, 90.0) is None                 # still under 10 done AND under 10%
    assert R.eta_s(10, 301, 100.0) is not None            # clears ETA_MIN_DONE
    assert R.eta_s(5, 20, 20.0) is not None               # 25%: clears ETA_MIN_FRAC despite < 10 done
    assert R.eta_s(30, 301, 150.0) == pytest.approx((301 - 30) * 150.0 / 30)


def test_progress_step_does_not_write_an_eta_before_the_gate(w):
    """Progress.step persists eta_s straight from refresh.eta_s: the stored
    scout_refresh row (and so ScoutStatus/the web badge) must not show a
    number before the gate opens."""
    conn = store.connect(w["db"])
    rid = "gatetest"
    assert store.try_begin_refresh(conn, rid, R.now_ms(), "test") is None   # claims the slot, inserts the row
    prog = R.Progress(conn, rid)
    prog.begin("stats", 301)
    prog.step(3, 301)
    r = conn.execute("SELECT eta_s FROM scout_refresh WHERE refresh_id = ?", (rid,)).fetchone()
    assert r["eta_s"] is None
    prog.step(31, 301)                                     # 31/301 ~= 10.3%: clears ETA_MIN_FRAC
    r2 = conn.execute("SELECT eta_s FROM scout_refresh WHERE refresh_id = ?", (rid,)).fetchone()
    assert r2["eta_s"] is not None


# ── rotation: every wallet refreshed within two passes ──────────────────────

def test_every_wallet_rotates_through_within_two_passes(tmp_path):
    from test_scout_world import build_venue
    v = build_venue()
    conn = store.connect(tmp_path / "rotation.db")
    addrs = sorted(BOARD)
    # tight: room for a couple of cold wallets in the first pass, not all 6
    budget1 = stats.Budget(max_weight=stats.estimate_weight(False) * 2 + 1, max_s=60)
    res1 = stats.run_stage_b(conn, v, addrs, NOW, budget1)
    assert 0 < len(res1.done) < len(addrs), res1.done

    budget2 = stats.Budget(max_weight=1e9, max_s=60)
    res2 = stats.run_stage_b(conn, v, addrs, NOW, budget2)
    assert set(res1.done) | set(res2.done) == set(addrs)   # two passes cover the whole cohort
    assert set(res2.done[: len(res1.deferred)]) == set(res1.deferred)   # deferred wallets go first next pass


# ── per-pass instrumentation (p50/p95 weight/pages/seconds, top 5) ──────────

def test_stage_b_summary_is_logged_and_stored(tmp_path):
    from test_scout_world import build_venue
    v = build_venue()
    conn = store.connect(tmp_path / "summary.db")
    addrs = sorted(BOARD)
    stats.run_stage_b(conn, v, addrs, NOW, stats.Budget(1e9, 60))
    summary = store.meta_get(conn, "stage_b_summary")
    assert summary is not None
    assert summary["n"] == len(addrs) == summary["full_count"]   # every wallet was cold: a full pass
    assert summary["weight_p50"] > 0 and summary["weight_p95"] >= summary["weight_p50"]
    assert 0 < len(summary["top5"]) <= 5
    assert summary["top5"][0]["weight"] >= summary["top5"][-1]["weight"]   # sorted, most expensive first
