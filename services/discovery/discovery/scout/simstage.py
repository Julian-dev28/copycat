"""Stage C (sim) and the what-if path: one wallet's copy-sim at given
settings, plus its equity curve.

The pipeline per wallet mirrors discovery.runner.score_one_wallet (perp
filter, poll coalescing, reconstruct, HFT gate, candles for trip spans,
sim.simulate_wallet, scoring.score_candidate) but starts from fills already
cached by stage B and keeps the SimResult skip flags, which Copy Fit's
capacity part needs and score_one_wallet drops.

Sim curve: when sim.simulate_wallet accepts `curve_step_ms` (and returns
SimResult.curve as [(t_ms, equity)]), one run gives an hourly curve.
Until then the curve is exact but daily: the sim is causal, so a run over
the events up to T with window_end_ms=T ends with exactly the equity the
full run has at T. 30 prefix runs, each shorter than the full one.

what-if: cached fills and candles only. CacheOnlyVenue answers every
candle read with None, so candles_cache.build_series assembles what is on
disk and records nothing; max leverage comes from the map stage C stored.
Zero HL calls.
"""
from __future__ import annotations

import inspect
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from contracts.models import CurvePoint, LeverageMode, Settings
from contracts.venue import Venue

from .. import candles_cache, positions, scoring, sim
from .. import config as discovery_config
from .. import db as discovery_db
from . import config as C
from . import store
from .stats import CountingVenue

logger = logging.getLogger(__name__)

HFT_OPENS_PER_DAY = 100.0
SKIP_PREFIXES = ("worse_entry:", "margin_room:", "max_open_copies:", "max_leverage_unknown:")


def default_sizing() -> Any:
    from engine import sizing as engine_sizing  # lazy, as in discovery.runner
    return engine_sizing


class CacheOnlyVenue:
    """No network: candle reads miss, so only cached bars are used."""

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> None:
        return None

    def max_leverage(self, coin: str) -> int:
        return 0


@dataclass
class SimOutcome:
    fields: Dict[str, Any]                       # TraderScore sim fields + fills/coins stats
    curve: List[CurvePoint] = field(default_factory=list)
    coin_max_lev: Dict[str, int] = field(default_factory=dict)


def _sim_accepts_curve() -> bool:
    try:
        return "curve_step_ms" in inspect.signature(sim.simulate_wallet).parameters
    except (TypeError, ValueError):
        return False


def _unsimulated(flags: List[str], n_fills: int, opd: float, hold: Optional[float], coins: List[str]) -> Dict[str, Any]:
    return {"sim_return_pct": 0.0, "sim_max_drawdown_pct": 0.0, "sim_liquidations": 0, "sim_copies": 0,
            "sim_skipped_min_order": 0, "sim_fees_usd": 0.0, "score": scoring.UNSCORED,
            "sim_copy_capacity_pct": None, "flags": sorted(set(flags)), "fills_30d": n_fills,
            "opens_per_day": opd, "median_hold_h": hold, "coins": coins, "simulated": False}


def capacity_pct(copies: int, skipped_min: int, sim_flags: Sequence[str]) -> Optional[float]:
    """#32. copies / (copies + min-order skips + every other skipped open)."""
    other = sum(1 for f in sim_flags if f.startswith(SKIP_PREFIXES))
    den = copies + skipped_min + other
    return round(copies / den * 100.0, 4) if den > 0 else None


def simulate(conn: sqlite3.Connection, venue: Any, fills: List[Dict[str, Any]], settings: Settings,
             sim_equity: float, leader_equity: float, lev_by_coin: Dict[str, float], now_ms: int,
             sizing: Any, coin_max_lev: Optional[Dict[str, int]] = None, cache_only: bool = False) -> SimOutcome:
    ws = now_ms - C.WINDOW_DAYS * C.DAY_MS
    flags: List[str] = []
    perp, other = positions.split_perp(fills)
    if other:
        flags.append("non_perp_ignored")
    by_coin = positions.reconstruct(positions.coalesce_by_poll(perp, int(settings.poll_interval_s * 1000)))
    opd = positions.opens_per_day(by_coin, C.WINDOW_DAYS)
    hold, _ = positions.median_hold_hours(by_coin)
    coins = positions.coins_traded(by_coin)
    n = len(fills)
    if opd > HFT_OPENS_PER_DAY:
        return SimOutcome(_unsimulated(flags + ["hft", "hft_not_simulated"], n, opd, hold, coins))
    spans = positions.trip_spans(by_coin, now_ms)
    if not spans:
        return SimOutcome(_unsimulated(flags + ["too_few_trades"], n, opd, hold, coins))

    known = dict(coin_max_lev or {})
    max_lev: Dict[str, int] = {}
    series: Dict[str, candles_cache.Series] = {}
    for coin, sp in spans.items():
        lev = int(known.get(coin) or 0)
        if lev < 1 and not cache_only:
            lev = int(venue.max_leverage(coin) or 0)
        max_lev[coin] = lev
        if lev < 1:
            continue
        series[coin], ok = candles_cache.build_series(conn, venue, coin, sp, now_ms, discovery_config.CACHE_FRESH_S)
        if not ok and not cache_only:
            flags.append(f"candles_partial:{coin}")

    events = [e for e in positions.merged_timeline(by_coin) if e.time_ms >= ws]
    his_lev = lev_by_coin if settings.leverage_mode == LeverageMode.match else {}

    def run(evs: Sequence[Any], end_ms: int, **kw: Any) -> Any:
        return sim.simulate_wallet(events=list(evs), series=series, coin_max_lev=max_lev,
                                   leader_equity_usd=leader_equity, leader_leverage_by_coin=his_lev,
                                   settings=settings, sim_equity_usd=sim_equity, window_end_ms=end_ms,
                                   sizing=sizing, **kw)

    if _sim_accepts_curve():
        r = run(events, now_ms, curve_step_ms=C.SIM_CURVE_STEP_MS)
        curve = [CurvePoint(t_ms=int(t), value=round(float(v), 4)) for t, v in (getattr(r, "curve", None) or [])]
    else:
        r = run(events, now_ms)
        curve = prefix_curve(events, now_ms, sim_equity, run, r)

    flags.extend(sorted({f for f in r.flags if f.startswith(("liquidated:", "max_leverage_unknown:"))}))
    sc = scoring.score_candidate(r.sim_return_pct, r.sim_max_drawdown_pct, r.sim_liquidations, r.sim_copies)
    flags.extend(sc.flags)
    fields_ = {"sim_return_pct": round(r.sim_return_pct, 4), "sim_max_drawdown_pct": round(r.sim_max_drawdown_pct, 4),
               "sim_liquidations": r.sim_liquidations, "sim_copies": r.sim_copies,
               "sim_skipped_min_order": r.sim_skipped_min_order, "sim_fees_usd": round(r.sim_fees_usd, 6),
               "score": round(sc.score, 6),
               "sim_copy_capacity_pct": capacity_pct(r.sim_copies, r.sim_skipped_min_order, r.flags),
               "flags": sorted(set(flags)), "fills_30d": n, "opens_per_day": opd, "median_hold_h": hold,
               "coins": coins, "simulated": True}
    return SimOutcome(fields_, curve, {c: v for c, v in max_lev.items() if v >= 1})


def prefix_curve(events: Sequence[Any], now_ms: int, sim_equity: float,
                 run: Callable[..., Any], full: Any) -> List[CurvePoint]:
    """Daily equity of the simulated copier: start, each UTC-day step, now."""
    ws = now_ms - C.WINDOW_DAYS * C.DAY_MS
    step = C.SIM_CURVE_FALLBACK_STEP_MS
    pts: List[Tuple[int, float]] = [(ws, sim_equity)]
    first = events[0].time_ms if events else now_ms
    t = ws + step
    while t < now_ms:
        if t < first:
            pts.append((t, sim_equity))
        else:
            r = run([e for e in events if e.time_ms <= t], t)
            pts.append((t, sim_equity * (1.0 + r.sim_return_pct / 100.0)))
        t += step
    pts.append((now_ms, sim_equity * (1.0 + full.sim_return_pct / 100.0)))
    return [CurvePoint(t_ms=t, value=round(v, 4)) for t, v in pts]


def wallet_inputs(conn: sqlite3.Connection, address: str) -> Optional[Dict[str, Any]]:
    """What a sim needs from stage B: cached fills over the stats window,
    the leader's equity and per-coin leverage. None without stats."""
    st = store.stats_row(conn, address)
    if not st or not st.get("updated_ms"):
        return None
    acct = json.loads(st["account_json"] or "{}")
    now = int(st["updated_ms"])
    u = store.universe_row(conn, address) or {}
    equity = float(u.get("account_value") or acct.get("equity_perp_usd") or 0.0)
    return {"now_ms": now, "stats_ms": now, "leader_equity": equity, "lev_by_coin": acct.get("lev_by_coin") or {},
            "fills": discovery_db.get_cached_fills(conn, address, now - C.WINDOW_DAYS * C.DAY_MS, now)}


@dataclass
class StageCResult:
    done: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    up_to_date: int = 0
    weight: float = 0.0


def run_stage_c(conn: sqlite3.Connection, venue: Venue, addresses: Sequence[str], settings: Settings,
                sim_equity: float, settings_hash: str, budget: Any, sizing: Any, limit: Optional[int] = None,
                progress: Optional[Callable[[int, int], None]] = None) -> StageCResult:
    """Sim every wallet whose stats are newer than its sim at (settings_hash,
    sim_equity). Candles are fetched through the shared cache (background
    priority); max leverage per coin is remembered in scout_meta for what-if."""
    res = StageCResult()
    have = store.sim_index(conn, settings_hash, sim_equity)
    stats_ix = store.stats_index(conn)
    todo = [a for a in addresses if stats_ix.get(a, {}).get("updated_ms")
            and have.get(a, -1) < int(stats_ix[a]["updated_ms"])]
    res.up_to_date = len([a for a in addresses if a in have and a not in todo])
    if limit is not None:
        res.deferred = todo[limit:]
        todo = todo[:limit]
    known = store.meta_get(conn, "coin_max_lev", {}) or {}
    for i, a in enumerate(todo):
        if not budget.allows(C.W_CANDLES):
            res.deferred = todo[i:] + res.deferred
            break
        inp = wallet_inputs(conn, a)
        if inp is None:
            continue
        cv = CountingVenue(venue)
        try:
            out = simulate(conn, cv, inp["fills"], settings.for_leader(a), sim_equity, inp["leader_equity"],
                           inp["lev_by_coin"], inp["now_ms"], sizing, coin_max_lev=known)
            store.save_sim(conn, a, settings_hash, sim_equity, int(time.time() * 1000), inp["stats_ms"],
                           out.fields, [p.model_dump(mode="json") for p in out.curve])
            if out.coin_max_lev:
                known.update(out.coin_max_lev)
                store.meta_set(conn, {"coin_max_lev": known})
            res.done.append(a)
        except Exception as exc:
            logger.warning("scout stage C: sim failed for %s: %s", a, exc, exc_info=True)
            res.failed.append(a)
        budget.charge(cv.weight)
        res.weight += cv.weight
        if progress:
            progress(i + 1, len(todo))
    return res
