"""Live eval (marked `live`, excluded from the gate): a small REAL Scout
refresh against Hyperliquid, read-only, background HL priority.

    .venv/bin/python -m pytest services/discovery/tests/test_scout_live.py -m live -s

Stage A (full leaderboard), stage B for 10 wallets, stage C for 5, publish.
Pass criteria:
  - scout_page returns the 10 wallets with stats; every row has every metric
    populated, or an explicit flag saying why not (not_simulated, hft, ...)
  - the 5 simulated rows have sim fields, a sim spark and a Copy Fit
  - portfolio sanity (spec 10): our 30d PnL (portfolio month pnlHistory, last
    point) matches the leaderboard month PnL within 2% (or $50) for >= 90%
  - runtime printed
"""
from __future__ import annotations

import json
import time

import pytest
from discovery.scout import metrics as M
from discovery.scout import public, store
from discovery.scout import refresh as R

from contracts.models import Settings


@pytest.mark.live
def test_scout_live_small_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_SCOUT_PROGRESS_DIR", str(tmp_path / "progress"))
    public.use_background_priority()
    from hl import HlVenue
    venue = HlVenue()
    db = tmp_path / "discovery.db"
    public.configure(db_path=db, venue=venue)

    t0 = time.time()
    rep = R.run_refresh(venue, Settings(), 1_000.0,
                        R.RefreshOptions(limit_b=10, limit_c=5, allow_partial=True, kind="eval"), db_path=db)
    took = time.time() - t0
    print(f"\nscout live: {took:.1f}s {json.dumps(rep.__dict__)}")
    assert rep.universe > 0 and rep.stats_done >= 9 and rep.sims_done >= 4

    t1 = time.time()
    page = public.scout_page({"sort": "fit", "limit": 50})
    print(f"scout live: scout_page {1000 * (time.time() - t1):.1f} ms, total={page.total}")
    assert page.total == rep.stats_done and page.cohort_size == rep.stats_done

    simulated = 0
    for r in page.rows:
        s = r.score
        flags = set(r.flags)
        assert s.copy_fit is not None and len(r.perf) == 4 and r.pnl_spark_30d
        assert r.risk_30d.days > 0 and r.risk_30d.max_drawdown_pct is not None
        assert r.risk_30d.sharpe is not None or r.risk_30d.days < 7
        assert r.last_fill_ms is not None or "inactive" in flags
        assert r.trades_30d.trips > 0 or flags & {"inactive", "too_few_trades", "hft"}
        assert r.top_coins or "inactive" in flags
        if "not_simulated" not in flags:
            simulated += 1                       # C ran: real sim numbers, or a flag saying why not
            assert s.sim_copies > 0 or flags & {"too_few_trades", "hft_not_simulated"}
        if s.sim_copies > 0:
            assert r.sim_spark_30d and s.sim_copy_capacity_pct is not None
        print(f"  {r.address} fit={s.copy_fit.value:5.1f} sim={s.sim_return_pct:7.2f}% "
              f"dd30={r.risk_30d.max_drawdown_pct} sharpe={r.risk_30d.sharpe} win={r.trades_30d.win_rate_pct} "
              f"trips={r.trades_30d.trips} style={r.style.value if r.style else '-'} flags={','.join(r.flags) or '-'}")
    assert simulated == rep.sims_done

    conn = store.connect(db)
    ok = n = 0
    for r in page.rows:
        st = store.stats_row(conn, r.address)
        port = M.parse_portfolio(json.loads(st["portfolio_json"]))
        ours = (port.get("month") or {}).get("pnl") or [[0, 0.0]]
        theirs = r.perf[2].pnl_usd
        n += 1
        ok += abs(ours[-1][1] - theirs) <= max(50.0, 0.02 * abs(theirs))
    print(f"scout live: portfolio vs leaderboard 30d PnL within 2%: {ok}/{n}")
    assert ok / n >= 0.9

    prof = public.scout_profile(page.rows[0].address)
    assert prof is not None and prof.row.address == page.rows[0].address and prof.daily_pnl
