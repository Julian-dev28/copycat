"""Stage B: per-wallet stats (spec 7.2), budgeted.

Per wallet: `portfolio` (20), `account_state` (~8), `extras` (~22), and an
incremental `userFillsByTime` sync through discovery's fills cache (120 per
page). From those, deterministic metrics (scout.metrics) into scout_stats.

All-or-nothing per wallet: if any read fails, nothing is written for it
(its previous stats keep serving), fail_count goes up, and at 2 failures in
a row it sits out one cycle and its row is flagged `stale`.

Order: wallets in the user's book first, then on-demand requests, then
stalest first (never-built wallets count as stalest). The pass stops at the
first wallet whose estimated weight would cross the budget, or when the wall
clock budget is spent; the rest go first next pass.

The budget is charged by what the wallet ACTUALLY called (CountingVenue),
weights per services/hl/hl/rate_limit.py.
"""
from __future__ import annotations

import inspect
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from contracts.models import PnlWindow
from contracts.venue import Venue

from .. import config as discovery_config
from .. import fills_cache
from . import config as C
from . import metrics as M
from . import store

logger = logging.getLogger(__name__)


def _params(fn: Any) -> Sequence[str]:
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return []


class CountingVenue:
    """Wraps a Venue and charges HL weight for every read made through it."""

    def __init__(self, venue: Venue) -> None:
        self._v = venue
        self.weight = 0.0
        self.calls: Dict[str, int] = {}

    def _charge(self, name: str, w: float) -> None:
        self.weight += w
        self.calls[name] = self.calls.get(name, 0) + 1

    def portfolio(self, user: str) -> Any:
        self._charge("portfolio", C.W_PORTFOLIO)
        return self._v.portfolio(user)

    def account_state(self, user: str) -> Any:
        self._charge("account_state", C.W_ACCOUNT_STATE)
        return self._v.account_state(user)

    def extras(self, user: str) -> Any:
        self._charge("extras", C.W_EXTRAS)
        return self._v.extras(user)

    def fills(self, user: str, start_ms: int, end_ms: int, aggregate_by_time: Optional[bool] = None) -> Any:
        # fills_cache passes aggregate_by_time only when the signature has it; forward it
        # only when the wrapped venue takes it too.
        if aggregate_by_time is not None and "aggregate_by_time" in _params(self._v.fills):
            rows = self._v.fills(user, start_ms, end_ms, aggregate_by_time=aggregate_by_time)
        else:
            rows = self._v.fills(user, start_ms, end_ms)
        pages = max(1, math.ceil(len(rows or []) / 2000))
        self._charge("fills", C.W_FILLS_PAGE * pages)
        return rows

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Any:
        rows = self._v.candles(coin, interval, start_ms, end_ms)
        self._charge("candles", C.W_CANDLES + math.ceil(len(rows or []) / 60))
        return rows

    def __getattr__(self, name: str) -> Any:     # max_leverage, leaderboard, ...: uncharged / meta-cached
        return getattr(self._v, name)


@dataclass
class Budget:
    """Weight + wall-clock budget for one stage pass. `clock` is injectable
    so the tests do not sleep."""
    max_weight: float
    max_s: float
    clock: Callable[[], float] = time.monotonic
    spent: float = 0.0
    started: float = field(default=-1.0)

    def __post_init__(self) -> None:
        if self.started < 0:
            self.started = self.clock()

    def allows(self, estimate: float) -> bool:
        if self.clock() - self.started >= self.max_s:
            return False
        return self.spent + estimate <= self.max_weight

    def charge(self, w: float) -> None:
        self.spent += w


def estimate_weight(has_stats: bool) -> float:
    """A cold wallet pulls 30 d of fills (often 2+ pages); a warm one one tail page."""
    fills = C.W_FILLS_PAGE * (3 if not has_stats else 1)
    return C.W_PORTFOLIO + C.W_ACCOUNT_STATE + C.W_EXTRAS + fills


def order_wallets(addresses: Sequence[str], index: Dict[str, Dict[str, Any]], book: Sequence[str],
                  requested: Sequence[str], now_ms: int) -> List[str]:
    """Book first, then on-demand requests, then stalest first (ties, e.g.
    every never-built wallet, keep the caller's order: best 30d PnL first). Wallets
    sitting out a failure cycle (skip_until_ms in the future) are left out."""
    book_set, req_set = set(book), set(requested)
    rank = {a: i for i, a in reversed(list(enumerate(addresses)))}   # caller's order (universe: 30d PnL desc)

    def key(a: str):
        i = index.get(a) or {}
        tier = 0 if a in book_set else (1 if a in req_set else 2)
        return (tier, int(i.get("updated_ms") or 0), rank[a])

    out = []
    for a in sorted(set(addresses), key=key):
        if int((index.get(a) or {}).get("skip_until_ms") or 0) > now_ms:
            continue
        out.append(a)
    return out


def compute_stats(portfolio: Any, fills: List[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    """Every portfolio and fills metric for one wallet, as JSON-ready dicts."""
    port = M.parse_portfolio(portfolio)
    risk = {}
    for name, win in (("week", PnlWindow.week), ("month", PnlWindow.month), ("allTime", PnlWindow.all_time)):
        w = port.get(name) or {}
        risk[win.value] = M.risk_stats(win, w.get("pnl") or [], w.get("av") or []).model_dump(mode="json")
    trips = M.round_trips(fills)
    trades = {w.value: M.trade_stats(w, trips, fills, now_ms).model_dump(mode="json")
              for w in (PnlWindow.week, PnlWindow.month)}
    t30 = trades["30d"]
    style = M.classify_style(t30["opens_per_day"], t30["median_hold_h"], t30["trips"])
    ws30 = now_ms - C.WINDOW_DAYS * C.DAY_MS
    fills30 = [f for f in fills if int(f["time_ms"]) >= ws30]
    trips30 = [t for t in trips if t.opened_ms >= ws30]
    coins = M.coin_stats(fills30, trips30)
    calendar = M.daily_pnl(port, now_ms)
    month = port.get("month") or {}
    flags: List[str] = []
    if M.fills_truncated(fills30, ws30):
        flags.append("fills_truncated")
    if style is not None and style.value == "algo":
        flags.append("hft")
    perp, other = M.positions.split_perp(fills30)
    if other:
        flags.append("non_perp_ignored")
    return {
        "risk": risk, "trades": trades, "style": style.value if style else None,
        "coins": [c.model_dump(mode="json") for c in coins],
        "hip3_share": round(M.hip3_share(coins), 6),
        "last_fill_ms": M.last_fill_ms(fills),
        "fills_30d": len(fills30),
        "calendar": [p.model_dump(mode="json") for p in calendar],
        "longest_win_streak_days": M.longest_win_streak_days(calendar),
        "recent_trips": [t.model_dump(mode="json") for t in trips[-C.RECENT_MAX:]][::-1],
        "pnl_spark_30d": [p.model_dump(mode="json")
                          for p in M.downsample(M.curve(month.get("pnl") or []), C.SPARK_MAX_POINTS)],
        "flags": flags,
    }


def build_wallet(conn: sqlite3.Connection, venue: CountingVenue, address: str, now_ms: int,
                 source_if_new: Optional[str] = None) -> None:
    """Stage B for one wallet. Raises on any failed read (caller records it)."""
    portfolio = venue.portfolio(address)
    if portfolio is None:
        raise RuntimeError("portfolio read failed")
    state = venue.account_state(address)
    if state is None:
        raise RuntimeError("account_state read failed")
    extras = venue.extras(address)        # optional: None leaves spot-other / staked at 0
    fills = fills_cache.sync_fills(conn, venue, address, C.WINDOW_DAYS, now_ms,   # type: ignore[arg-type]
                                   discovery_config.CACHE_FRESH_S)
    stats = compute_stats(portfolio, fills, now_ms)
    if extras is None:
        stats["flags"].append("extras_unavailable")
    views = M.position_views(state.get("raw_positions") or {})
    acct = M.account_risk(state, extras, views).model_dump(mode="json")
    account = {"risk": acct, "lev_by_coin": {c: float(p.get("lev") or 0) for c, p in
                                             (state.get("positions") or {}).items()},
               "equity_perp_usd": float(state.get("equity_perp_usd") or 0.0)}
    store.save_stats(conn, address, now_ms, portfolio, account, [v.model_dump(mode="json") for v in views], stats)
    if source_if_new and store.universe_row(conn, address) is None:
        port = M.parse_portfolio(portfolio)
        row: Dict[str, Any] = {"address": address, "display_name": None, "is_vault": 0, "source": source_if_new,
                               "seen_ms": now_ms,
                               "account_value": float(state.get("equity_perp_usd") or 0.0)
                               + float(state.get("spot_usdc") or 0.0)}
        for name, suf in (("day", "1d"), ("week", "7d"), ("month", "30d"), ("allTime", "all")):
            pnl, roi, vlm = M.window_perf_from_portfolio(port, name)
            row.update({f"pnl_{suf}": pnl, f"roi_{suf}": roi, f"vlm_{suf}": vlm})
        store.upsert_universe(conn, row)


@dataclass
class StageResult:
    done: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    weight: float = 0.0


def run_stage_b(conn: sqlite3.Connection, venue: Venue, addresses: Sequence[str], now_ms: int, budget: Budget,
                book: Sequence[str] = (), requested: Sequence[str] = (), limit: Optional[int] = None,
                progress: Optional[Callable[[int, int], None]] = None,
                clock_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> StageResult:
    index = store.stats_index(conn)
    order = order_wallets(addresses, index, book, requested, now_ms)
    if limit is not None:
        order = order[:limit]
    res = StageResult()
    book_set, req_set = set(book), set(requested)
    for i, a in enumerate(order):
        est = estimate_weight(a in index and bool(index[a].get("updated_ms")))
        if not budget.allows(est):
            res.deferred = order[i:]
            logger.info("scout stage B: budget reached (%.0f weight), %d wallets deferred", budget.spent,
                        len(res.deferred))
            break
        cv = CountingVenue(venue)
        t = clock_ms()
        try:
            src = "book" if a in book_set else ("ondemand" if a in req_set else None)
            build_wallet(conn, cv, a, t, source_if_new=src)
            res.done.append(a)
        except Exception as exc:
            n = store.record_stats_failure(conn, a, t, f"{type(exc).__name__}: {exc}", int(C.STAGE_B_EVERY_S * 1000))
            logger.warning("scout stage B: %s failed (%d in a row): %s", a, n, exc)
            res.failed.append(a)
        budget.charge(cv.weight)
        res.weight += cv.weight
        if progress:
            progress(i + 1, len(order))
    return res
