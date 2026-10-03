"""Live eval, not a gate test (excluded by pyproject's `-m 'not live'`
default). A small REAL discovery run against the live Hyperliquid
leaderboard through hl.HlVenue -- read-only, no signed/exchange calls
(discovery never writes).

Run explicitly:
    .venv/bin/python -m pytest services/discovery/tests/test_live.py -m live -v -s

Pass criteria (per the task spec): no exceptions, every candidate comes
back scored or flagged with a reason, and the run's wall-clock time is
reported.
"""
from __future__ import annotations

import time

import pytest

from contracts.models import LeverageMode, MarginMode, Settings, SizingMode
from discovery import public


@pytest.mark.live
def test_live_small_real_run():
    from hl import HlVenue
    venue = HlVenue()

    settings = Settings(
        sizing_mode=SizingMode.fixed_margin,
        fixed_margin_usd=1.0,
        leverage_mode=LeverageMode.max,
        margin_mode=MarginMode.isolated,
    )

    started = time.time()
    run_id = public.start_run(settings, sim_equity_usd=100.0, top_n=5, venue=venue, window_days=7)
    print(f"\nlive eval: run {run_id} started (top_n=5, 7d window, equity=$100, "
          f"fixed_margin=$1, leverage=max)")

    run = None
    deadline = time.time() + 540
    while time.time() < deadline:
        run = public.get_run(run_id)
        if run is not None and run.status in ("done", "failed"):
            break
        time.sleep(1.0)
    elapsed = time.time() - started

    assert run is not None, "run never reached a terminal status within the deadline"
    print(f"live eval: finished in {elapsed:.1f}s, status={run.status}, "
          f"candidates={run.candidates}, scored={run.scored}")
    assert run.status == "done", f"run failed: {run.error}"
    assert run.candidates > 0, "leaderboard returned no eligible candidates at the default filters"
    assert run.scored == run.candidates

    for r in run.results:
        has_sim_data = r.sim_copies > 0 or r.sim_return_pct != 0.0
        is_flagged = bool(r.flags)
        assert has_sim_data or is_flagged, f"{r.address} neither simulated nor flagged with a reason"

    ranked = sorted(run.results, key=lambda r: r.score, reverse=True)
    print(f"\n{'#':>3}  {'address':<42}  {'score':>9}  {'ret%':>8}  {'dd%':>8}  "
          f"{'cop':>4}  liq  {'fees':>7}  flags")
    for i, r in enumerate(ranked, start=1):
        print(f"{i:>3}  {r.address}  {r.score:>9.2f}  {r.sim_return_pct:>7.2f}%  "
              f"{r.sim_max_drawdown_pct:>7.2f}%  {r.sim_copies:>4}  {r.sim_liquidations:>3}  "
              f"${r.sim_fees_usd:>6.3f}  {','.join(r.flags) or '-'}")
    print(f"\nlive eval: total runtime {elapsed:.1f}s for {run.candidates} candidates")
