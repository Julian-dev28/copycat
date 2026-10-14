"""Stage C (sim) and the what-if path: one wallet's copy-sim at given
settings, plus its equity curve.

Same pipeline as /discover: runner.prepare_wallet (perp filter, poll
coalescing, reconstruct, HFT gate, candles for trip spans) then
runner.simulate_prepared (sim.simulate_wallet, raw SimResult with its skip
flags, which Copy Fit's capacity part needs and score_one_wallet drops).
Scout starts from fills already cached by stage B, and the leader's
per-coin leverage comes from stage B's stored account read (_KnownLeverage),
not a fresh account_state call.

Sim curve: ONE run with curve_step_ms=1h and window_start_ms=window start
returns the copier's marked equity every hour (flat at sim_equity before his
first in-window event) plus the final point. This replaced 30 daily prefix
re-runs.

what-if: cached fills and candles only. CacheOnlyVenue answers every
candle read with None, so candles_cache.build_series assembles what is on
disk and records nothing; max leverage comes from the map stage C stored.
Zero HL calls.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from contracts.models import CurvePoint, Settings
from contracts.venue import Venue

from .. import config as discovery_config
from .. import db as discovery_db
from .. import runner, scoring
from . import config as C
from . import store
from .stats import CountingVenue

logger = logging.getLogger(__name__)

SKIP_PREFIXES = ("worse_entry:", "margin_room:", "max_open_copies:", "max_leverage_unknown:")
CAPACITY_NOTE_MAX_PCT = 80.0      # below this, explain the dominant skip reason (user_consensus P0 #2)

_SKIP_REASON_TEXT = {
    "min_order": "under the $10.50 minimum order at your size",
    "worse_entry:": "price had already moved past your worse-entry limit",
    "margin_room:": "not enough free margin at your settings",
    "max_open_copies:": "already at your max open copies",
    "max_leverage_unknown:": "max leverage unknown for a coin they traded",
}


def default_sizing() -> Any:
    from engine import sizing as engine_sizing  # lazy, as in discovery.runner
    return engine_sizing


class CacheOnlyVenue:
    """No network: candle reads miss, so only cached bars are used."""

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> None:
        return None

    def max_leverage(self, coin: str) -> int:
        return 0


class _KnownLeverage:
    """What runner.simulate_prepared reads for leverage_mode=match
    (account_state(addr)["positions"][coin]["lev"]), served from stage B's
    stored per-coin leverage: no HL call, same numbers Scout always used."""

    def __init__(self, lev_by_coin: Dict[str, float]) -> None:
        self._pos = {c: {"lev": float(v)} for c, v in (lev_by_coin or {}).items()}

    def account_state(self, user: str) -> Dict[str, Any]:
        return {"positions": self._pos}


@dataclass
class SimOutcome:
    fields: Dict[str, Any]                       # TraderScore sim fields + fills/coins stats
    curve: List[CurvePoint] = field(default_factory=list)
    coin_max_lev: Dict[str, int] = field(default_factory=dict)


def _unsimulated(flags: List[str], n_fills: int, opd: float, hold: Optional[float], coins: List[str]) -> Dict[str, Any]:
    return {"sim_return_pct": 0.0, "sim_max_drawdown_pct": 0.0, "sim_liquidations": 0, "sim_copies": 0,
            "sim_skipped_min_order": 0, "sim_fees_usd": 0.0, "score": scoring.UNSCORED,
            "sim_copy_capacity_pct": None, "sim_capacity_note": None, "flags": sorted(set(flags)),
            "fills_30d": n_fills, "opens_per_day": opd, "median_hold_h": hold, "coins": coins,
            "simulated": False}


def capacity_pct(copies: int, skipped_min: int, sim_flags: Sequence[str]) -> Optional[float]:
    """#32. copies / (copies + min-order skips + every other skipped open)."""
    other = sum(1 for f in sim_flags if f.startswith(SKIP_PREFIXES))
    den = copies + skipped_min + other
    return round(copies / den * 100.0, 4) if den > 0 else None


def capacity_reason(copies: int, skipped_min: int, sim_flags: Sequence[str]) -> Optional[str]:
    """One plain-language line naming the dominant reason capacity is low
    (user_consensus P0 #2: show this before 'Add to book', not only buried
    in an expand row). None when there is nothing to explain: no skips, or
    capacity is already at/above CAPACITY_NOTE_MAX_PCT."""
    counts: Dict[str, int] = {"min_order": skipped_min}
    for prefix in SKIP_PREFIXES:
        counts[prefix] = sum(1 for f in sim_flags if f.startswith(prefix))
    total_skips = sum(counts.values())
    den = copies + total_skips
    if den <= 0 or total_skips <= 0:
        return None
    pct = copies / den * 100.0
    if pct >= CAPACITY_NOTE_MAX_PCT:
        return None
    key, n = max(counts.items(), key=lambda kv: kv[1])
    if n <= 0:
        return None
    share = round(n / total_skips * 100.0)
    return f"{share}% of skipped opens: {_SKIP_REASON_TEXT[key]}"


def simulate(conn: sqlite3.Connection, venue: Any, fills: List[Dict[str, Any]], settings: Settings,
             sim_equity: float, leader_equity: float, lev_by_coin: Dict[str, float], now_ms: int,
             sizing: Any, coin_max_lev: Optional[Dict[str, int]] = None, cache_only: bool = False) -> SimOutcome:
    ws = now_ms - C.WINDOW_DAYS * C.DAY_MS
    p = runner.prepare_wallet(conn, venue, fills, settings, C.WINDOW_DAYS, now_ms, include_hft=False,
                              fresh_s=discovery_config.CACHE_FRESH_S, coin_max_lev=coin_max_lev,
                              cache_only=cache_only)
    if p.skip is not None:
        return SimOutcome(_unsimulated(p.flags + p.skip, p.n_fills, p.opens_per_day, p.median_hold_h, p.coins))

    r = runner.simulate_prepared(p, _KnownLeverage(lev_by_coin), "", settings, sim_equity, leader_equity, sizing,
                                 now_ms, curve_step_ms=C.SIM_CURVE_STEP_MS, window_start_ms=ws)
    curve = [CurvePoint(t_ms=int(t), value=round(float(v), 4)) for t, v in (r.curve or [])]

    flags = list(p.flags)
    flags.extend(sorted({f for f in r.flags if f.startswith(("liquidated:", "max_leverage_unknown:"))}))
    sc = scoring.score_candidate(r.sim_return_pct, r.sim_max_drawdown_pct, r.sim_liquidations, r.sim_copies)
    flags.extend(sc.flags)
    fields_ = {"sim_return_pct": round(r.sim_return_pct, 4), "sim_max_drawdown_pct": round(r.sim_max_drawdown_pct, 4),
               "sim_liquidations": r.sim_liquidations, "sim_copies": r.sim_copies,
               "sim_skipped_min_order": r.sim_skipped_min_order, "sim_fees_usd": round(r.sim_fees_usd, 6),
               "score": round(sc.score, 6),
               "sim_copy_capacity_pct": capacity_pct(r.sim_copies, r.sim_skipped_min_order, r.flags),
               "sim_capacity_note": capacity_reason(r.sim_copies, r.sim_skipped_min_order, r.flags),
               "flags": sorted(set(flags)), "fills_30d": p.n_fills, "opens_per_day": p.opens_per_day,
               "median_hold_h": p.median_hold_h, "coins": p.coins, "simulated": True}
    return SimOutcome(fields_, curve, {c: v for c, v in p.coin_max_lev.items() if v >= 1})


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


def run_stage_c(conn: sqlite3.Connection, venue: Venue, addresses: Sequence[str],
                get_settings: Union[Settings, Callable[[str], Settings]],
                sim_equity: float, settings_hash: str, budget: Any, sizing: Any, limit: Optional[int] = None,
                progress: Optional[Callable[[int, int], None]] = None,
                allow_cache_only: bool = False) -> StageCResult:
    """Sim every wallet whose stats are newer than its sim at (settings_hash,
    sim_equity). Candles are fetched through the shared cache (background
    priority); max leverage per coin is remembered in scout_meta for what-if.

    `get_settings`: a Settings (old callers, kept for a plain Settings
    argument) or a per-wallet callable (refresh.effective_settings_for_leader):
    Settings.for_leader(wallet) under live settings, or the same ScoutSimTerms-
    derived Settings for every wallet otherwise.

    `allow_cache_only`: True for a ScoutSimTerms (not live-settings) run. A
    wallet that already has a sim at ANY hash (store.simmed_addresses) has its
    trip-span candles cached already -- a terms change never needs a new HL
    call for it, so it sims on CacheOnlyVenue (zero HL weight). A wallet with
    no prior sim (first board build, or a brand new custom wallet) always gets
    the real venue, whatever allow_cache_only says."""
    settings_for = get_settings if callable(get_settings) else get_settings.for_leader
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
    cache_ok = store.simmed_addresses(conn, todo) if allow_cache_only else set()
    for i, a in enumerate(todo):
        if not budget.allows(C.W_CANDLES):
            res.deferred = todo[i:] + res.deferred
            break
        inp = wallet_inputs(conn, a)
        if inp is None:
            continue
        cache_only = a in cache_ok
        cv = CountingVenue(CacheOnlyVenue() if cache_only else venue)
        try:
            out = simulate(conn, cv, inp["fills"], settings_for(a), sim_equity, inp["leader_equity"],
                           inp["lev_by_coin"], inp["now_ms"], sizing, coin_max_lev=known, cache_only=cache_only)
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
