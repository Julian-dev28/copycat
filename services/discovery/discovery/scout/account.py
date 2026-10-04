"""account_metrics(address): the Account page's metric fields for ANY
address, on demand, from the same Scout metric functions the board uses.

Called from the api process in a worker thread, so it is bounded:
- one portfolio read (weight 20) and a 30-day fills sync through the shared
  fills cache, at hl's background priority;
- the fills sync runs in its own thread with ACCOUNT_FILLS_TIMEOUT_S; past
  that, the answer goes out without the fills-based fields (trades_30d,
  style, holds) and the sync keeps filling the cache for the next call;
- the fills pages themselves are bounded by hl's own pagination cap; the
  timeout bounds how long the caller waits for them;
- results are cached in-process for ACCOUNT_TTL_S (5 min) per address, and
  only one computation per address is in flight.

Keys are AccountSummary field names (contracts.models); values are JSON-ready.
Portfolio failure -> None (the api then shows the page without metrics).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, Dict, List, Optional, Tuple

from contracts.models import PnlWindow

from .. import db as discovery_db
from .. import fills_cache
from . import metrics as M

logger = logging.getLogger(__name__)

ACCOUNT_TTL_S = 300.0
ACCOUNT_FILLS_TIMEOUT_S = 20.0
ACCOUNT_CURVE_MAX_POINTS = 200
WINDOW_DAYS = 30
DAY_MS = 86_400_000

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_inflight: Dict[str, threading.Lock] = {}
_guard = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="account-fills")


def clear_cache() -> None:
    with _guard:
        _cache.clear()


def _sync_fills(db_path: Any, venue: Any, address: str, now_ms: int) -> List[Dict[str, Any]]:
    conn = discovery_db.connect(db_path)   # this thread's own connection
    return fills_cache.sync_fills(conn, venue, address, WINDOW_DAYS, now_ms)


def compute(portfolio: Any, fills: Optional[List[Dict[str, Any]]], now_ms: int) -> Dict[str, Any]:
    """Pure: the metric dict from a raw HL portfolio and (optionally) fills."""
    port = M.parse_portfolio(portfolio)
    pnl_all, _roi, vlm_all = M.window_perf_from_portfolio(port, "allTime")
    all_av = (port.get("allTime") or {}).get("av") or []
    month = port.get("month") or {}
    calendar = M.daily_pnl(port, now_ms)
    out: Dict[str, Any] = {
        "all_time_pnl_usd": round(pnl_all, 6),
        "volume_usd": round(vlm_all, 6),
        "longest_win_streak_days": M.longest_win_streak_days(calendar),
        "pnl_tier": M.pnl_tier(pnl_all).value,
        "size_tier": M.size_tier(all_av[-1][1] if all_av else 0.0).value,
        "risk_30d": M.risk_stats(PnlWindow.month, month.get("pnl") or [], month.get("av") or []).model_dump(mode="json"),
        "pnl_curve": {}, "value_curve": {},
        "daily_pnl": [p.model_dump(mode="json") for p in calendar],
        "style": None, "avg_hold_h": None, "median_hold_h": None, "trades_30d": None,
    }
    for name, win in M.PORTFOLIO_WINDOWS.items():
        w = port.get(name) or {}
        out["pnl_curve"][win.value] = [p.model_dump(mode="json") for p in
                                       M.downsample(M.curve(w.get("pnl") or []), ACCOUNT_CURVE_MAX_POINTS)]
        out["value_curve"][win.value] = [p.model_dump(mode="json") for p in
                                         M.downsample(M.curve(w.get("av") or []), ACCOUNT_CURVE_MAX_POINTS)]
    if fills is not None:
        trips = M.round_trips(fills)
        ts = M.trade_stats(PnlWindow.month, trips, fills, now_ms)
        style = M.classify_style(ts.opens_per_day, ts.median_hold_h, ts.trips)
        out.update(trades_30d=ts.model_dump(mode="json"), style=style.value if style else None,
                   avg_hold_h=ts.avg_hold_h, median_hold_h=ts.median_hold_h)
    return out


def account_metrics(address: str, venue: Any, db_path: Any, now_ms: Optional[int] = None,
                    fills_timeout_s: float = ACCOUNT_FILLS_TIMEOUT_S,
                    clock: Callable[[], float] = time.time) -> Optional[Dict[str, Any]]:
    a = address.strip().lower()
    with _guard:
        hit = _cache.get(a)
        if hit is not None and clock() - hit[0] <= ACCOUNT_TTL_S:
            return hit[1]
        lock = _inflight.setdefault(a, threading.Lock())
    with lock:   # one computation per address; a second caller waits and then reads the cache
        with _guard:
            hit = _cache.get(a)
            if hit is not None and clock() - hit[0] <= ACCOUNT_TTL_S:
                return hit[1]
        now_ms = now_ms if now_ms is not None else int(clock() * 1000)
        portfolio = venue.portfolio(a)
        if portfolio is None:
            return None
        fut = _pool.submit(_sync_fills, db_path, venue, a, now_ms)
        fills: Optional[List[Dict[str, Any]]]
        try:
            fills = fut.result(timeout=fills_timeout_s)
        except FutureTimeout:
            logger.warning("account_metrics(%s): fills sync over %.0fs, answering without trade stats", a,
                           fills_timeout_s)
            fills = None
        except Exception as exc:
            logger.warning("account_metrics(%s): fills read failed: %s", a, type(exc).__name__)
            fills = None
        out = compute(portfolio, fills, now_ms)
        out["as_of_ms"] = now_ms
        if fills is not None:   # a partial answer is not cached: the next call can complete it
            with _guard:
                _cache[a] = (clock(), out)
        return out
