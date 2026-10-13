"""Scout board: universe selection, row contents, filters, sorts, paging,
presets, all through public.scout_page with the api's exact query shape."""
from __future__ import annotations

import pytest
from discovery.scout import public
from discovery.scout import refresh as R
from discovery.scout.query import ScoutQueryError
from test_scout_world import BOARD, DAY, EQUITY, NOW, CC, A, B, D, E, G, build_venue, q, settings, world


@pytest.fixture
def w(tmp_path, monkeypatch):
    return world(tmp_path, monkeypatch)


def addrs(page):
    return [r.address for r in page.rows]


def test_universe_filters_and_book(w):
    p = public.scout_page(q())
    assert set(addrs(p)) == BOARD and p.total == 6 and p.cohort_size == 6
    assert not p.stale_settings and p.refresh_id and p.settings_hash


def test_every_row_metric_populated(w):
    for r in public.scout_page(q()).rows:
        s = r.score
        assert s.copy_fit is not None and s.copy_fit.cohort_size == 6
        assert set(s.copy_fit.parts) == set(s.copy_fit.weights)
        assert r.risk_30d.sharpe is not None and r.risk_30d.max_drawdown_pct is not None
        assert r.trades_30d.trips > 0 and r.trades_30d.win_rate_pct is not None
        assert r.top_coins and r.pnl_spark_30d and r.sim_spark_30d and r.last_fill_ms
        assert len(r.perf) == 4 and s.sim_copy_capacity_pct is not None
    row = {r.address: r for r in public.scout_page(q()).rows}
    assert row[A].display_name == "Alpha" and row[A].size_tier.value == "L" and row[CC].pnl_tier.value == "elite"
    assert row[D].style is None and "too_few_trades" in row[D].flags        # 2 trips


def test_sorts_and_order(w):
    fits = [r.score.copy_fit.value for r in public.scout_page(q()).rows]
    assert fits == sorted(fits, reverse=True)
    assert addrs(public.scout_page(q(sort="account_value")))[0] == E
    assert addrs(public.scout_page(q(sort="account_value", order="asc")))[-1] == E
    assert addrs(public.scout_page(q(sort="pnl")))[0] == A
    assert addrs(public.scout_page(q(sort="trips")))[0] == A
    for s in ("sim_return", "sim_dd", "roi", "sharpe", "max_dd", "win_rate", "last_active", "volume"):
        assert public.scout_page(q(sort=s)).total == 6


def test_filters(w):
    assert set(addrs(public.scout_page(q(min_av=100_000)))) == {A, E}
    assert set(addrs(public.scout_page(q(max_av=25_000)))) == {D, G}
    assert addrs(public.scout_page(q(min_pnl=8_500))) == [A]
    assert addrs(public.scout_page(q(max_pnl=0))) == [G]
    assert public.scout_page(q(window="7d", min_pnl=5)).total == 6
    assert set(addrs(public.scout_page(q(coin=["ETH"])))) == {B, E}
    assert addrs(public.scout_page(q(preset="hip3"))) == [CC]
    assert set(addrs(public.scout_page(q(preset="coin:BTC")))) == {A, D}
    assert set(addrs(public.scout_page(q(min_trips=10)))) == {A, B}
    assert addrs(public.scout_page(q(style=["position"]))) == []
    assert D not in addrs(public.scout_page(q(style=["intraday"])))
    assert public.scout_page(q(active_within_h=24)).total == 0
    assert public.scout_page(q(active_within_h=24 * 8)).total == 6
    assert addrs(public.scout_page(q(q="alp"))) == [A]
    assert addrs(public.scout_page(q(q=A))) == [A]
    top = public.scout_page(q(limit=1)).rows[0].score.copy_fit.value
    assert public.scout_page(q(min_fit=top)).total == 1 and public.scout_page(q(max_fit=0)).total == 0
    assert public.scout_page(q(max_dd=0.06)).total == 1


def test_hide_flagged(w, monkeypatch):
    from discovery.scout import store
    conn = store.connect(w["db"])
    ptr = store.pointer(conn)
    conn.execute("UPDATE scout_rows SET flagged = 1 WHERE refresh_id = ? AND address = ?", (ptr["refresh_id"], B))
    conn.commit()
    assert B not in addrs(public.scout_page(q(hide_flagged=True)))


def test_paging_is_stable(w):
    full = addrs(public.scout_page(q(sort="win_rate")))
    pages = [addrs(public.scout_page(q(sort="win_rate", limit=2, offset=o))) for o in (0, 2, 4)]
    assert sum(pages, []) == full


@pytest.mark.parametrize("bad", [dict(window="2d"), dict(sort="nope"), dict(order="up"), dict(limit=0),
                                 dict(limit=201), dict(offset=-1), dict(style=["yolo"]), dict(min_av="x"),
                                 dict(min_av=5, max_av=1), dict(preset="coin:")])
def test_bad_query_raises(w, bad):
    with pytest.raises(ScoutQueryError):
        public.scout_page(q(**bad))


def test_in_book_flag_and_presets(w):
    rows = {r.address: r for r in public.scout_page({**q(), "in_book": [G.upper().replace("0X", "0x")]}).rows}
    assert rows[G].in_book and not rows[A].in_book
    pr = public.scout_presets()
    assert pr.total == 6 and pr.hip3_count == 1 and pr.coins[0] in ("BTC", "ETH")
    assert pr.coin_counts == {"BTC": 2, "ETH": 2, "xyz:TSLA": 1, "SOL": 1}


def test_empty_board_before_first_build(tmp_path):
    public.configure(db_path=tmp_path / "empty.db")
    p = public.scout_page(q())
    assert p.total == 0 and p.rows == [] and public.scout_presets().total == 0


def test_wallet_liquidated_flag_is_real_not_sim(tmp_path, monkeypatch):
    """user_consensus P0 #3: a wallet that was ACTUALLY liquidated (HL fill
    dir "Liquidated ...") shows liquidations_30d/last_liquidation_ms and the
    "wallet_liquidated" flag on its row, and Copy Fit is capped -- all from
    one extra fill, with no change to the copy-sim's own sim_liquidations."""
    monkeypatch.setenv("COPYCAT_SCOUT_PROGRESS_DIR", str(tmp_path / "progress"))
    v = build_venue()
    liq_ms = NOW - 2 * DAY
    v.set_fills(A, v._fills[A] + [{"time_ms": liq_ms, "coin": "BTC", "px": 100.0, "sz": 1.0, "side": "A",
                                   "dir": "Liquidated Isolated Long", "start_position": 1.0,
                                   "closed_pnl": -500.0, "fee": 1.0}])
    db = tmp_path / "discovery.db"
    public.configure(db_path=db, venue=v)
    R.run_refresh(v, settings(), EQUITY, db_path=db)
    row = {r.address: r for r in public.scout_page(q()).rows}[A]
    assert row.score.liquidations_30d == 1 and row.score.last_liquidation_ms == liq_ms
    assert "wallet_liquidated" in row.flags and "wallet_liquidated" in row.score.copy_fit.caps
    assert row.score.copy_fit.value <= 50
    assert row.score.sim_liquidations == 0                     # the copy-sim itself never got liquidated
