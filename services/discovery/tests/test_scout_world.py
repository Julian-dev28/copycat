"""A small Scout world for the pipeline gate tests (no tests here):
leaderboard, portfolios, fills, 15m candles, one book wallet."""
from __future__ import annotations

from typing import Any, Dict

from discovery.scout import public
from discovery.scout import refresh as R
from test_scout_helpers import DAY, NOW, ScoutVenue, addr, flat_15m, lb_row, portfolio, trips

from contracts.models import Settings, SizingMode

A, B, CC, D, E, V, F, G = (addr(i) for i in range(1, 9))
BOARD = {A, B, CC, D, E, G}
EQUITY = 1_000.0


def settings(**kw: Any) -> Settings:
    base = dict(sizing_mode=SizingMode.fixed_margin, fixed_margin_usd=1.0, leaders=[G])
    base.update(kw)
    return Settings(**base)


def build_venue() -> ScoutVenue:
    v = ScoutVenue()
    v.set_leaderboard([
        lb_row(A, 200_000, 9_000, 50_000, name="Alpha"),
        lb_row(B, 50_000, 8_000, 20_000),
        lb_row(CC, 30_000, 7_000, 2_000_000),
        lb_row(D, 20_000, 6_000, 1_000),
        lb_row(E, 5_000_000, 5_000, -10_000),          # losing all time, up this month: kept
        {**lb_row(V, 900_000, 99_000, 99_000), "isVault": True},   # vault: out
        lb_row(F, 5_000, 4_000, 4_000),                # under $10k: out
        lb_row(G, 5_000, -1, -1),                      # fails filters but is in the book: kept
    ])
    start = NOW - 25 * DAY
    plan = {A: ("BTC", 20, 0.01), B: ("ETH", 12, 0.02), CC: ("xyz:TSLA", 8, 0.01), D: ("BTC", 2, -0.01),
            E: ("ETH", 6, 0.005), G: ("SOL", 5, 0.01)}
    for k, (w, (coin, n, move)) in enumerate(plan.items()):
        first = NOW - 5 * DAY - (n - 1) * DAY          # last trip closes ~5 days ago: active
        v.set_fills(w, trips(coin, n, first, pnl=50.0 * (1 if move > 0 else -1), move=move))
        v.set_portfolio(w, portfolio([0] + [40.0 + 10 * k, -10.0 - 5 * k, 25.0] * 13, av=20_000.0))
        v.set_account_state(w, {"equity_perp_usd": 20_000.0, "spot_usdc": 0.0, "positions": {},
                                "raw_positions": {}})
    for coin, px in (("BTC", 100.0), ("ETH", 100.0), ("xyz:TSLA", 100.0), ("SOL", 100.0)):
        v.set_candles(coin, "15m", flat_15m(px * 1.005, start - DAY, NOW))
    return v


def world(tmp_path, monkeypatch) -> Dict[str, Any]:
    monkeypatch.setenv("COPYCAT_SCOUT_PROGRESS_DIR", str(tmp_path / "progress"))
    v = build_venue()
    db = tmp_path / "discovery.db"
    public.configure(db_path=db, venue=v)
    rep = R.run_refresh(v, settings(), EQUITY, db_path=db)
    return {"venue": v, "db": db, "report": rep}


def q(**kw: Any) -> Dict[str, Any]:
    """The api's exact query shape: every key present, unset = None."""
    base = {"window": "30d", "preset": "all", "coin": [], "min_av": None, "max_av": None, "min_pnl": None,
            "max_pnl": None, "style": [], "min_fit": None, "max_fit": None, "max_dd": None, "min_trips": None,
            "active_within_h": None, "hide_flagged": False, "q": None, "sort": "fit", "order": "desc",
            "limit": 50, "offset": 0}
    base.update(kw)
    return base
