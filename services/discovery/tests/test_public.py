from __future__ import annotations

import threading
import time

import pytest

from contracts.models import Settings
from discovery import config, public, runner

from discovery_fakes import FakeVenue


def leaderboard_row(address):
    return {
        "ethAddress": address, "accountValue": "100000", "displayName": None, "isVault": False,
        "windowPerformances": [
            ["month", {"pnl": "5000", "roi": "0.1", "vlm": "60000"}],
            ["allTime", {"pnl": "20000", "roi": "1.0", "vlm": "600000"}],
        ],
    }


def test_run_lifecycle_start_get_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "discovery_lifecycle.db")
    venue = FakeVenue()
    venue.set_leaderboard([leaderboard_row("0xAAA"), leaderboard_row("0xBBB")])
    # no fills configured -> both candidates hit the "no in-window events" path: fast, deterministic

    run_id = public.start_run(Settings(), sim_equity_usd=100.0, top_n=5, venue=venue, window_days=1,
                               min_account_value_usd=0, min_volume_30d_usd=0)

    run = _wait_done(run_id)
    assert run.status == "done"
    assert run.candidates == 2
    assert run.scored == 2
    assert len(run.results) == 2
    assert {r.address for r in run.results} == {"0xaaa", "0xbbb"}
    assert all("too_few_trades" in r.flags for r in run.results)

    latest = public.latest()
    assert latest is not None
    assert latest.run_id == run_id


def test_only_one_run_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "discovery_lock.db")
    started = threading.Event()
    release = threading.Event()

    def blocking_execute(conn, venue, run_id, settings, sim_equity_usd, top_n, *args, **kwargs):
        started.set()
        release.wait(timeout=5)
        from discovery import db
        db.update_run(conn, run_id, status="done", finished_ms=int(time.time() * 1000))

    monkeypatch.setattr(runner, "execute", blocking_execute)

    venue = FakeVenue()
    run_id1 = public.start_run(Settings(), sim_equity_usd=100.0, top_n=1, venue=venue)
    assert started.wait(timeout=2)

    with pytest.raises(RuntimeError):
        public.start_run(Settings(), sim_equity_usd=100.0, top_n=1, venue=venue)

    release.set()
    _wait_done(run_id1)


def _wait_done(run_id, timeout_s=5.0):
    deadline = time.time() + timeout_s
    run = None
    while time.time() < deadline:
        run = public.get_run(run_id)
        if run is not None and run.status in ("done", "failed"):
            return run
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish within {timeout_s}s (last={run})")
