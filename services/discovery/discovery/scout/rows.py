"""Assembly: universe + stats + sim -> Copy Fit over the cohort -> TraderRow
-> scout_rows under a new refresh_id -> switch. And the TraderProfile blob
for the trader file. Pure assembly over stored data: no HL calls.

Cohort = every universe wallet (sources lb + book) that has stage-B stats.
A wallet with stats but no sim at the board's settings_hash is served with
the `not_simulated` flag and sim part 0, never with made-up sim numbers.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from contracts.models import (
    AccountRisk,
    CoinStat,
    CopyFit,
    CurvePoint,
    LeaderFillView,
    PnlWindow,
    RiskStats,
    RoundTrip,
    TraderPositionView,
    TraderProfile,
    TraderRow,
    TraderScore,
    TradeStats,
    TradingStyle,
    WindowPerf,
)

from .. import db as discovery_db
from . import coattail as CT
from . import config as C
from . import copy_fit, store
from . import metrics as M

HIDE_FLAGS = ("liquidated", "wallet_liquidated", "hft", "vault", "inactive", "coattail")
_WIN = (("1d", PnlWindow.day), ("7d", PnlWindow.week), ("30d", PnlWindow.month), ("all", PnlWindow.all_time))
_PW = {"day": PnlWindow.day, "week": PnlWindow.week, "month": PnlWindow.month, "allTime": PnlWindow.all_time}
_SFX = {PnlWindow.day: "1d", PnlWindow.week: "7d", PnlWindow.month: "30d", PnlWindow.all_time: "all"}


def _loads(s: Optional[str], default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _unsim_fields(stats: Dict[str, Any]) -> Dict[str, Any]:
    coins = sorted(c["coin"] for c in stats.get("coins") or [])
    t30 = (stats.get("trades") or {}).get("30d") or {}
    return {"sim_return_pct": 0.0, "sim_max_drawdown_pct": 0.0, "sim_liquidations": 0, "sim_copies": 0,
            "sim_skipped_min_order": 0, "sim_fees_usd": 0.0, "score": -200.0, "sim_copy_capacity_pct": None,
            "sim_capacity_note": None, "flags": ["not_simulated"], "fills_30d": int(stats.get("fills_30d") or 0),
            "opens_per_day": float(t30.get("opens_per_day") or 0.0), "median_hold_h": t30.get("median_hold_h"),
            "coins": coins, "simulated": False}


def _flags(u: Dict[str, Any], stats: Dict[str, Any], sim: Dict[str, Any], stats_meta: Dict[str, Any],
           now_ms: int, is_coattail: bool = False) -> List[str]:
    f = set(stats.get("flags") or []) | set(sim.get("flags") or [])
    if u.get("is_vault"):
        f.add("vault")
    stale_age = now_ms - int(stats_meta.get("updated_ms") or 0) > 3 * C.STAGE_B_EVERY_S * 1000
    if int(stats_meta.get("fail_count") or 0) >= C.FAILS_BEFORE_SKIP or stale_age:
        f.add("stale")
    # user_consensus P0 #3: the wallet's OWN real liquidations, surfaced as its own flag
    # (distinct from "liquidated", which is the copy-SIM getting liquidated).
    if int(stats.get("liquidations_30d") or 0) > 0:
        f.add("wallet_liquidated")
    if is_coattail:
        f.add("coattail")
    return sorted(f)


def fit_input(u: Dict[str, Any], stats: Dict[str, Any], sim: Dict[str, Any], flags: Sequence[str]) -> copy_fit.FitInput:
    r30 = (stats.get("risk") or {}).get("30d") or {}
    t30 = (stats.get("trades") or {}).get("30d") or {}
    return copy_fit.FitInput(
        address=u["address"], account_value_usd=float(u.get("account_value") or 0.0),
        sim_score=sim.get("score") if sim.get("simulated") else None,
        sharpe_30d=r30.get("sharpe"), max_drawdown_30d_pct=r30.get("max_drawdown_pct"),
        profitable_days_pct_30d=r30.get("profitable_days_pct"), win_rate_30d_pct=t30.get("win_rate_pct"),
        trips_30d=int(t30.get("trips") or 0), copy_capacity_pct=sim.get("sim_copy_capacity_pct"),
        last_fill_ms=stats.get("last_fill_ms"), sim_liquidations=int(sim.get("sim_liquidations") or 0),
        sim_copies=int(sim.get("sim_copies") or 0), flags=list(flags))


def make_row(u: Dict[str, Any], stats: Dict[str, Any], sim: Dict[str, Any], sim_curve: Sequence[Dict[str, Any]],
             flags: Sequence[str], fit: Optional[CopyFit],
             coattail: Optional[Tuple[str, float, int]] = None, custom: bool = False) -> TraderRow:
    style = TradingStyle(stats["style"]) if stats.get("style") else None
    all_flags = sorted(set(flags) | set(fit.caps if fit else []))
    score = TraderScore(
        address=u["address"], display_name=u.get("display_name"),
        account_value_usd=float(u.get("account_value") or 0.0), pnl_30d_usd=float(u.get("pnl_30d") or 0.0),
        roi_30d_pct=float(u.get("roi_30d") or 0.0), pnl_all_time_usd=float(u.get("pnl_all") or 0.0),
        volume_30d_usd=float(u.get("vlm_30d") or 0.0), fills_30d=int(sim.get("fills_30d") or 0),
        opens_per_day=float(sim.get("opens_per_day") or 0.0), median_hold_h=sim.get("median_hold_h"),
        coins=list(sim.get("coins") or []), sim_return_pct=float(sim["sim_return_pct"]),
        sim_max_drawdown_pct=float(sim["sim_max_drawdown_pct"]), sim_liquidations=int(sim["sim_liquidations"]),
        sim_copies=int(sim["sim_copies"]), sim_skipped_min_order=int(sim["sim_skipped_min_order"]),
        sim_fees_usd=float(sim["sim_fees_usd"]), score=float(sim["score"]), flags=all_flags,
        sim_copy_capacity_pct=sim.get("sim_copy_capacity_pct"), copy_fit=fit, style=style,
        last_fill_ms=stats.get("last_fill_ms"),
        liquidations_30d=int(stats.get("liquidations_30d") or 0),
        last_liquidation_ms=stats.get("last_liquidation_ms"),
        sim_capacity_note=sim.get("sim_capacity_note"),
        coattail_leader=coattail[0] if coattail else None,
        coattail_share_pct=round(coattail[1] * 100.0, 1) if coattail else None)
    av = float(u.get("account_value") or 0.0)
    return TraderRow(
        address=u["address"], display_name=u.get("display_name"), account_value_usd=av,
        size_tier=M.size_tier(av), pnl_tier=M.pnl_tier(float(u.get("pnl_all") or 0.0)), style=style,
        last_fill_ms=stats.get("last_fill_ms"),
        perf=[WindowPerf(window=w, pnl_usd=float(u.get(f"pnl_{s}") or 0.0), roi_pct=float(u.get(f"roi_{s}") or 0.0),
                         volume_usd=float(u.get(f"vlm_{s}") or 0.0)) for s, w in _WIN],
        risk_30d=RiskStats(**((stats.get("risk") or {}).get("30d") or {"window": "30d"})),
        trades_30d=TradeStats(**((stats.get("trades") or {}).get("30d")
                                 or {"window": "30d", "trips": 0, "wins": 0, "long_trips": 0, "short_trips": 0})),
        top_coins=[CoinStat(**c) for c in (stats.get("coins") or [])[:5]],
        pnl_spark_30d=[CurvePoint(**p) for p in (stats.get("pnl_spark_30d") or [])][: C.SPARK_MAX_POINTS],
        sim_spark_30d=M.downsample([CurvePoint(**p) for p in sim_curve], C.SPARK_MAX_POINTS),
        score=score, in_book=False, flags=all_flags, custom=custom)


def sql_row(row: TraderRow, refresh_id: str, settings_hash: str, u: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    coins = [c.coin for c in row.top_coins]
    d: Dict[str, Any] = {
        "refresh_id": refresh_id, "settings_hash": settings_hash, "address": row.address,
        "display_name": (row.display_name or "").lower() or None,
        "fit": row.score.copy_fit.value if row.score.copy_fit else None,
        "sim_return": row.score.sim_return_pct, "sim_dd": row.score.sim_max_drawdown_pct,
        "account_value": row.account_value_usd,
        "sharpe": row.risk_30d.sharpe, "max_dd": row.risk_30d.max_drawdown_pct,
        "win_rate": row.trades_30d.win_rate_pct, "trips": row.trades_30d.trips,
        "style": row.style.value if row.style else None, "size_tier": row.size_tier.value,
        "last_fill_ms": row.last_fill_ms, "top_coin": coins[0] if coins else None,
        "hip3_share": float(stats.get("hip3_share") or 0.0),
        "coins_csv": "," + ",".join(coins) + "," if coins else "",
        "flags_csv": "," + ",".join(row.flags) + "," if row.flags else "",
        "flagged": int(any(f.split(":")[0] in HIDE_FLAGS for f in row.flags)),
        "sim_copies": int(row.score.sim_copies),      # v18: preset=copyable
        "row_json": row.model_dump_json(),
    }
    for p in row.perf:
        s = _SFX[p.window]
        d[f"pnl_{s}"], d[f"roi_{s}"], d[f"vlm_{s}"] = p.pnl_usd, p.roi_pct, p.volume_usd
    return d


def _load_stats(conn: sqlite3.Connection, addresses: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for a in addresses:
        r = conn.execute("SELECT updated_ms, fail_count, stats_json FROM scout_stats WHERE address = ? "
                         "AND updated_ms IS NOT NULL", (a,)).fetchone()
        if r is not None:
            out[a] = {"meta": {"updated_ms": r["updated_ms"], "fail_count": r["fail_count"]},
                      "stats": _loads(r["stats_json"], {})}
    return out


def _load_sims(conn: sqlite3.Connection, settings_hash: str, sim_equity: float) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute("SELECT address, score_json, sim_curve_json FROM scout_sim WHERE settings_hash = ? "
                        "AND sim_equity = ?", (settings_hash, sim_equity)).fetchall()
    return {r["address"]: {"fields": _loads(r["score_json"], {}), "curve": _loads(r["sim_curve_json"], [])}
            for r in rows}


def _coattail_map(conn: sqlite3.Connection, addresses: Sequence[str],
                  now_ms: int) -> Dict[str, Tuple[str, float, int]]:
    """Cohort-wide coattail detection (user_consensus P1 #6) over each
    wallet's cached 30d fills. Pure CPU over data stage B already fetched:
    no HL calls. Any address whose fills can't be read is skipped, never
    treated as "no opens" (that would falsely clear a real coattail match
    for everyone it leads)."""
    ws = now_ms - C.WINDOW_DAYS * C.DAY_MS
    opens: List[CT.Open] = []
    for a in addresses:
        try:
            fills = discovery_db.get_cached_fills(conn, a, ws, now_ms)
        except Exception:
            continue
        opens.extend(CT.opens_from_fills(a, fills))
    return CT.detect_coattails(opens)


def build(conn: sqlite3.Connection, refresh_id: str, settings_hash: str, sim_equity: float, now_ms: int) -> int:
    """Write a full board for refresh_id, then switch to it. Returns the cohort size."""
    uni = store.universe(conn)                      # lb + book + custom rows
    custom = set(store.custom_addresses(conn))
    stats = _load_stats(conn, [u["address"] for u in uni])
    sims = _load_sims(conn, settings_hash, sim_equity)
    cohort = [u for u in uni if u["address"] in stats]
    coattails = _coattail_map(conn, [u["address"] for u in cohort], now_ms)
    prepared = []
    for u in cohort:
        a = u["address"]
        st = stats[a]["stats"]
        sim = (sims.get(a) or {}).get("fields") or _unsim_fields(st)
        flags = _flags(u, st, sim, stats[a]["meta"], now_ms, is_coattail=a in coattails)
        prepared.append((u, st, sim, (sims.get(a) or {}).get("curve") or [], flags))
    fits = copy_fit.compute([fit_input(u, st, sim, fl) for u, st, sim, _, fl in prepared], now_ms)
    out = []
    for u, st, sim, curve, flags in prepared:
        a = u["address"]
        row = make_row(u, st, sim, curve, flags, fits[a], coattail=coattails.get(a), custom=a in custom)
        out.append(sql_row(row, refresh_id, settings_hash, u, st))
    store.write_rows(conn, out)
    store.switch(conn, refresh_id, settings_hash, now_ms, len(out), sim_equity)
    return len(out)


# ── trader file ───────────────────────────────────────────────────────────

def fill_view(f: Dict[str, Any]) -> LeaderFillView:
    """Regression, caught 2026-10-14 by the history_check eval against real
    HL data on a hyperactive wallet: `liquidation` here used to be HL's raw
    per-fill bool, which also fires on the COUNTERPARTY absorbing someone
    ELSE's liquidation (an ordinary "Open Long" fill, raw liquidation=true)
    -- 16 fills in the eval's served window read "Liquidated" for a wallet
    with exactly ONE real liquidation in that same window. Same `dir`-prefix
    check as discovery.scout.metrics.real_liquidations / discovery.positions
    (the fill's own `dir` says THIS account was force-closed/force-reduced;
    the raw bool only says a liquidation-engine fill touched the account at
    all, on EITHER side of the trade)."""
    px, sz = float(f["px"]), float(f["sz"])
    return LeaderFillView(time_ms=int(f["time_ms"]), coin=f["coin"], side="B" if f["side"] == "B" else "A",
                          dir=f.get("dir") or "", px=px, sz=sz, notional_usd=round(abs(px * sz), 2),
                          closed_pnl_usd=float(f.get("closed_pnl") or 0.0), fee_usd=float(f.get("fee") or 0.0),
                          liquidation=str(f.get("dir") or "").startswith("Liquidated"))


def recent_fills(conn: sqlite3.Connection, address: str, before_ms: Optional[int], limit: int) -> List[LeaderFillView]:
    """Newest first, strictly before before_ms (None = now), from the fills cache.

    A page never cuts a millisecond in half. The next page's cursor is this
    page's oldest fill's time_ms, read back EXCLUSIVE (`hi = before_ms - 1`
    on the next call): if that oldest fill's millisecond holds more rows
    than `limit`, trimming to exactly `limit` would strand the rest at that
    exact ms -- the next page's exclusive cursor would skip past all of
    them, the same silent gap HL's own userFillsByTime pagination guards
    against (services/hl/hl/venue.py `fills`). A TWAP or a leader with
    aggregateByTime fills across many coins/orders at one tick can plausibly
    put 50+ fills on one millisecond, so the page grows past `limit` rather
    than losing any."""
    hi = (before_ms - 1) if before_ms is not None else 2**62
    # through discovery.db's accessor, never its table name (the fills table is that module's to change)
    rows = discovery_db.get_cached_fills(conn, address, 0, hi)
    if not rows:
        return []
    cut = max(0, len(rows) - int(limit))
    boundary_t = rows[cut]["time_ms"]
    while cut > 0 and rows[cut - 1]["time_ms"] == boundary_t:
        cut -= 1
    return [fill_view(r) for r in rows[cut:][::-1]]


def _profile_sim(conn: sqlite3.Connection, address: str, ptr: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The sim at the board's hash; else at the newest hash (an on-demand
    file simulated at the current settings before the board republished)."""
    if ptr:
        s = store.sim_row(conn, address, ptr["settings_hash"], ptr["sim_equity"])
        if s:
            return s
    r = conn.execute("SELECT * FROM scout_sim WHERE address = ? ORDER BY updated_ms DESC LIMIT 1", (address,)).fetchone()
    return dict(r) if r else None


def profile(conn: sqlite3.Connection, address: str) -> Optional[TraderProfile]:
    st_row = store.stats_row(conn, address)
    if not st_row or not st_row.get("updated_ms"):
        return None
    stats = _loads(st_row["stats_json"], {})
    ptr = store.pointer(conn)
    custom = address in set(store.custom_addresses(conn))   # live from scout_custom: right from the add,
    row: Optional[TraderRow] = None                           # before the board is republished with the mark
    sim_curve: List[Dict[str, Any]] = []
    if ptr:
        rj = store.row_json(conn, ptr["refresh_id"], address)
        if rj:
            row = TraderRow.model_validate_json(rj)
            row.custom = custom
    sim = _profile_sim(conn, address, ptr)
    if sim:
        sim_curve = _loads(sim["sim_curve_json"], [])
    if row is None:                       # not on the board (on-demand file, or built after the last switch)
        u = store.universe_row(conn, address) or {"address": address, "account_value": 0.0}
        simf = (_loads(sim["score_json"], {}) if sim else {}) or _unsim_fields(stats)
        flags = _flags(u, stats, simf, {"updated_ms": st_row["updated_ms"], "fail_count": st_row["fail_count"]},
                       int(st_row["updated_ms"]))
        row = make_row(u, stats, simf, sim_curve, flags, None, custom=custom)
    port = M.parse_portfolio(_loads(st_row["portfolio_json"], []))
    acct = _loads(st_row["account_json"], {})
    risk = stats.get("risk") or {}
    trades = stats.get("trades") or {}
    return TraderProfile(
        row=row, account=AccountRisk(**acct["risk"]),
        positions=[TraderPositionView(**p) for p in _loads(st_row["positions_json"], [])],
        positions_as_of_ms=int(st_row["positions_ms"] or st_row["updated_ms"]),
        pnl_curve={w: M.curve((port.get(n) or {}).get("pnl") or []) for n, w in _PW.items()},
        value_curve={w: M.curve((port.get(n) or {}).get("av") or []) for n, w in _PW.items()},
        sim_curve=[CurvePoint(**p) for p in sim_curve],
        daily_pnl=[CurvePoint(**p) for p in stats.get("calendar") or []],
        risk=[RiskStats(**risk[k]) for k in ("7d", "30d", "all") if k in risk],
        trades=[TradeStats(**trades[k]) for k in ("7d", "30d") if k in trades],
        longest_win_streak_days=int(stats.get("longest_win_streak_days") or 0),
        coins=[CoinStat(**c) for c in stats.get("coins") or []],
        recent_trips=[RoundTrip(**t) for t in (stats.get("recent_trips") or [])[: C.RECENT_MAX]],
        recent_fills=recent_fills(conn, address, None, C.RECENT_MAX))
