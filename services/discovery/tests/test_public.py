from __future__ import annotations

import threading
import time

import pytest
from engine import sizing as real_sizing

from contracts.models import Settings
from discovery import config, db, public, runner

from discovery_fakes import FakeVenue


def leaderboard_row(address):
    return {
        "ethAddress": address, "accountValue": "100000", "displayName": None, "isVault": False,
        "windowPerformances": [
            ["month", {"pnl": "5000", "roi": "0.1", "vlm": "60000"}],
            ["allTime", {"pnl": "20000", "roi": "1.0", "vlm": "600000"}],
        ],
    }


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "discovery_public.db")


def test_run_lifecycle_start_get_latest():
    venue = FakeVenue()
    venue.set_leaderboard([leaderboard_row("0xAAA"), leaderboard_row("0xBBB")])
    run_id = public.start_run(Settings(), sim_equity_usd=100.0, top_n=5, venue=venue, window_days=1,
                              min_account_value_usd=0, min_volume_30d_usd=0, sizing_module=real_sizing)
    run = _wait_done(run_id)
    assert run.status == "done" and run.candidates == 2 and run.scored == 2
    assert {r.address for r in run.results} == {"0xaaa", "0xbbb"}
    assert all("too_few_trades" in r.flags and r.score == -200.0 for r in run.results)
    assert public.latest().run_id == run_id


def test_leaderboard_snapshot_is_reused_within_ttl():
    calls = []

    class V(FakeVenue):
        def leaderboard(self):
            calls.append(1)
            return [leaderboard_row("0xAAA")]

    for _ in range(2):
        _wait_done(public.start_run(Settings(), 100.0, top_n=5, venue=V(), window_days=1, min_account_value_usd=0,
                                    min_volume_30d_usd=0, sizing_module=real_sizing))
    assert len(calls) == 1


def test_only_one_run_at_a_time(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def blocking_execute(conn, venue, run_id, *args, **kwargs):
        started.set()
        release.wait(timeout=5)
        db.update_run(conn, run_id, status="done", finished_ms=int(time.time() * 1000))

    monkeypatch.setattr(runner, "execute", blocking_execute)
    run_id1 = public.start_run(Settings(), sim_equity_usd=100.0, top_n=1, venue=FakeVenue())
    assert started.wait(timeout=2)
    with pytest.raises(RuntimeError):
        public.start_run(Settings(), sim_equity_usd=100.0, top_n=1, venue=FakeVenue())
    release.set()
    _wait_done(run_id1)


def test_dead_worker_row_is_reaped_instead_of_blocking_forever(monkeypatch):
    stale = public.create_run(Settings(), 100.0, 5)
    conn = db.connect(config.DB_PATH)
    db.update_run(conn, stale, heartbeat_ms=int(time.time() * 1000) - int(config.STALE_RUN_S * 1000) - 1)
    venue = FakeVenue()
    fresh = public.start_run(Settings(), 100.0, top_n=1, venue=venue, sizing_module=real_sizing)
    _wait_done(fresh)
    assert public.get_run(stale).status == "failed"
    assert "heartbeat" in public.get_run(stale).error


def test_worker_executes_a_created_run_with_its_stored_options():
    venue = FakeVenue()
    venue.set_leaderboard([leaderboard_row("0xCCC")])
    run_id = public.create_run(Settings(), 100.0, 3, runner.RunOptions(window_days=2, min_account_value_usd=0,
                                                                       min_volume_30d_usd=0))
    public.run_worker(run_id, venue=venue, sizing_module=real_sizing)
    run = public.get_run(run_id)
    assert run.status == "done" and run.candidates == 1
    assert venue.fills_calls[0][2] - venue.fills_calls[0][1] == 2 * 86_400_000


def test_cli_worker_and_progress_line(capsys):
    from discovery import __main__ as cli
    venue = FakeVenue()
    run_id = public.create_run(Settings(), 100.0, 3)
    db.update_run(db.connect(config.DB_PATH), run_id, candidates=10, scored=4)
    line = cli.progress_line(public.get_run(run_id), 40.0)
    assert "4/10 scored" in line and "eta 60s" in line
    assert venue is not None


def _wait_done(run_id, timeout_s=5.0):
    deadline = time.time() + timeout_s
    run = None
    while time.time() < deadline:
        run = public.get_run(run_id)
        if run is not None and run.status in ("done", "failed"):
            return run
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish within {timeout_s}s (last={run})")
