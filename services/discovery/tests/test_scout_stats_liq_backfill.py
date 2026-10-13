"""Stage B wiring for the liquidation backfill (coordinator follow-up): a
wallet whose fills were cached before the `liquidation` column existed gets
corrected on its next profile build, and only once."""
from __future__ import annotations

import json

from discovery import db as discovery_db
from discovery.scout import stats, store
from test_scout_helpers import NOW, ScoutVenue, addr, fill, portfolio


def test_build_wallet_backfills_a_pre_migration_liquidation_then_never_again(tmp_path):
    conn = store.connect(tmp_path / "liq_backfill.db")
    A = addr(1)
    v = ScoutVenue()
    t = NOW - 10 * 86_400_000

    # Simulate a wallet already cached before the `liquidation` column existed: the row is
    # on disk with liquidation hard-0, same as every fill in a real pre-migration discovery.db.
    discovery_db.insert_fills(conn, A, [fill(t, "BTC", 100.0, 1.0, "B", 0.0)])
    discovery_db.set_fills_coverage(conn, A, t - 1, NOW, NOW)
    assert discovery_db.get_fills_coverage(conn, A)["liq_backfilled"] == 0

    v.set_portfolio(A, portfolio([0] * 31, av=20_000.0))
    v.set_account_state(A, {"equity_perp_usd": 20_000.0, "spot_usdc": 0.0, "positions": {}, "raw_positions": {}})
    # What HL actually says today for that same fill: it WAS a liquidation.
    liquidated_fill = dict(fill(t, "BTC", 100.0, 1.0, "B", 0.0))
    liquidated_fill["liquidation"] = True
    v.set_fills(A, [liquidated_fill])

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)

    row = discovery_db.get_cached_fills(conn, A, 0, NOW)[0]
    assert bool(row["liquidation"]) is True
    assert discovery_db.get_fills_coverage(conn, A)["liq_backfilled"] == 1
    calls_after_first_build = len(v.fills_calls)

    # Second profile build: must not refetch for the backfill again (the regular tail
    # sync may still run on a fresh-coverage miss, but the liquidation backfill itself
    # is a one-time, self-marking no-op from here on).
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW + 1_000)
    assert len(v.fills_calls) == calls_after_first_build

    st = store.stats_row(conn, A)
    assert json.loads(st["stats_json"])["recent_trips"] == []   # sanity: wallet still builds fine
