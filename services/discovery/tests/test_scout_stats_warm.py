"""Stage B warm path (indexing tightening, 2026-10): a wallet with stats
already on disk pays for portfolio + the fills tail most passes.
account_state, extras, userFunding and the liquidation backfill move to
config.FULL_REFRESH_EVERY_S -- unless a new fill just landed or this is
the wallet's first-ever build."""
from __future__ import annotations

import json

from discovery.scout import config as C, stats, store
from test_scout_helpers import DAY, HOUR, NOW, ScoutVenue, addr, fill, portfolio


def _seed(v: ScoutVenue, a: str, fills) -> None:
    v.set_portfolio(a, portfolio([0] * 31, av=20_000.0))
    v.set_account_state(a, {"equity_perp_usd": 20_000.0, "spot_usdc": 500.0, "positions": {}, "raw_positions": {}})
    v.set_fills(a, fills)


def test_cold_build_always_does_the_full_set(tmp_path):
    conn = store.connect(tmp_path / "cold.db")
    A = addr(1)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    assert v.account_state_calls == 1
    row = store.stats_row(conn, A)
    assert row["full_ms"] == NOW and row["updated_ms"] == NOW


def test_warm_pass_with_no_new_fills_skips_account_state_extras_and_funding(tmp_path):
    conn = store.connect(tmp_path / "warm.db")
    A = addr(2)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    assert v.account_state_calls == 1

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW + HOUR)
    assert v.account_state_calls == 1          # not re-read: no new fill, cadence not due

    row = store.stats_row(conn, A)
    assert row["full_ms"] == NOW                # the slow-cadence read did not move...
    assert row["updated_ms"] == NOW + HOUR       # ...but stats/portfolio did, every pass
    assert row["positions_ms"] == NOW            # positions snapshot is from the last full read


def test_a_new_fill_forces_a_full_pass_inside_the_cadence(tmp_path):
    conn = store.connect(tmp_path / "newfill.db")
    A = addr(3)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    assert v.account_state_calls == 1

    # a new fill lands an hour later, well inside FULL_REFRESH_EVERY_S (6h default)
    v.set_fills(A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0),
                    fill(NOW + HOUR - 60_000, "BTC", 101.0, 1.0, "A", 1.0, pnl=1.0)])
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW + HOUR)
    assert v.account_state_calls == 2            # the new fill forced the full set right away
    assert store.stats_row(conn, A)["full_ms"] == NOW + HOUR


def test_full_cadence_fires_even_with_no_new_fills(tmp_path):
    conn = store.connect(tmp_path / "cadence.db")
    A = addr(4)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    assert v.account_state_calls == 1

    later = NOW + int(C.FULL_REFRESH_EVERY_S * 1000) + HOUR
    stats.build_wallet(conn, stats.CountingVenue(v), A, later)
    assert v.account_state_calls == 2
    assert store.stats_row(conn, A)["full_ms"] == later


def test_warm_pass_carries_over_extras_unavailable(tmp_path, monkeypatch):
    conn = store.connect(tmp_path / "carry.db")
    A = addr(5)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    monkeypatch.setattr(v, "extras", lambda user: None)

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW)
    first = json.loads(store.stats_row(conn, A)["stats_json"])
    assert "extras_unavailable" in first["flags"]

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW + HOUR)
    second = json.loads(store.stats_row(conn, A)["stats_json"])
    assert "extras_unavailable" in second["flags"]   # carried over, even though extras was not re-read
    assert v.account_state_calls == 1                 # confirms this pass really was cheap


def test_warm_pass_keeps_refreshing_a_custom_wallets_universe_account_value(tmp_path):
    """Regression: build_wallet's universe-upsert tail used `state.get(...)` directly,
    which is None on a cheap pass -- crashed any custom/on-demand wallet's second,
    cheap build. account.get(...) (fresh on a full pass, carried over on a cheap one)
    must keep working either way."""
    conn = store.connect(tmp_path / "custom_warm.db")
    A = addr(6)
    v = ScoutVenue()
    _seed(v, A, [fill(NOW - 10 * DAY, "BTC", 100.0, 1.0, "B", 0.0)])
    cv = stats.CountingVenue(v)
    stats.build_wallet(conn, cv, A, NOW, source_if_new="custom")
    assert store.universe_row(conn, A)["account_value"] == 20_500.0   # equity + spot_usdc

    stats.build_wallet(conn, stats.CountingVenue(v), A, NOW + HOUR, source_if_new="custom")
    assert store.universe_row(conn, A)["account_value"] == 20_500.0   # did not crash, value carried over
