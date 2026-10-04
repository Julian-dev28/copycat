"""discovery.scout.public: the ONLY Scout surface other services import.

Request-path functions (api process, FastAPI threadpool) are sqlite reads
only and never call HL, except scout_orders (live, cached 30 s) by design:

    scout_page(query) -> TraderPage
    scout_profile(address) -> TraderProfile | ScoutStatus (queued, api: 202) | None (api: 404)
    scout_fills(address, before_ms, limit) -> List[LeaderFillView]
    scout_orders(address) -> List[dict]          live HL, 30 s cache; ScoutReadError on a failed read
    scout_what_if(address, settings, sim_equity_usd, override) -> WhatIfResult
                                                 cached fills/candles only, 0 HL calls, 1 concurrent
    scout_presets() -> dict
    scout_status() -> ScoutStatus
    scout_refresh() -> ScoutStatus               only signals `serve`; ScoutBusy when running/queued

The heavy work (stages A/B/C, board builds, on-demand trader files) runs in
`python -m discovery.scout serve` via run_scheduler(settings_provider).
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from contracts.models import (LeaderFillView, LeaderOverride, ScoutPresets, ScoutStatus, Settings, TraderPage, TraderProfile,
                              TraderRow, TraderScore, WhatIfResult, norm_addr)

from . import config as C
from . import query as Q
from . import refresh as R
from . import rows, simstage, store
from .query import ScoutQueryError
from .refresh import ScoutBusy, run_scheduler, settings_hash

__all__ = ["scout_page", "scout_profile", "scout_fills", "scout_orders", "scout_what_if", "scout_presets",
           "scout_status", "scout_refresh", "run_scheduler", "serve", "ScoutBusy", "ScoutQueryError",
           "ScoutReadError", "settings_hash", "configure"]

_ADDR = re.compile(r"^0x[0-9a-f]{40}$")


class ScoutReadError(RuntimeError):
    """A live HL read (open orders) failed. Never presented as 'no orders'."""


_cfg: Dict[str, Any] = {"db_path": None, "venue": None, "sizing": None}
_orders_cache: Dict[str, tuple] = {}
_orders_lock = threading.Lock()
_what_if_lock = threading.Lock()


def configure(db_path: Optional[Path] = None, venue: Any = None, sizing: Any = None) -> None:
    """Test/CLI hook: which db file, venue and sizing module to use."""
    _cfg.update(db_path=db_path, venue=venue, sizing=sizing)
    _orders_cache.clear()


def _conn():
    return store.connect(_cfg["db_path"])


def use_background_priority() -> None:
    os.environ["COPYCAT_HL_PRIORITY"] = "background"
    try:
        from hl import rate_limit
    except ImportError:
        return
    if getattr(getattr(rate_limit, "HL_LIMITER", None), "priority", None) != "background":
        rate_limit.set_priority("background")


def _default_venue() -> Any:
    if _cfg["venue"] is not None:
        return _cfg["venue"]
    use_background_priority()
    from hl import HlVenue
    _cfg["venue"] = HlVenue()
    return _cfg["venue"]


def _addr(address: str) -> Optional[str]:
    a = norm_addr(address)
    return a if _ADDR.match(a) else None


# ── board ─────────────────────────────────────────────────────────────────

def scout_page(query: Optional[Dict[str, Any]] = None) -> TraderPage:
    q = Q.parse(query)
    conn = _conn()
    ptr = store.pointer(conn)
    if ptr is None:
        return TraderPage(as_of_ms=0, refresh_id="", settings_hash="", cohort_size=0, total=0, rows=[])
    w, args = Q.where(q, ptr["refresh_id"])
    total = conn.execute(f"SELECT COUNT(*) FROM scout_rows WHERE {w}", args).fetchone()[0]
    rs = conn.execute(f"SELECT row_json FROM scout_rows WHERE {w} ORDER BY {Q.order_by(q)} LIMIT ? OFFSET ?",
                      args + [q.limit, q.offset]).fetchall()
    in_book = {norm_addr(a) for a in (query or {}).get("in_book") or []}
    out = []
    for r in rs:
        row = TraderRow.model_validate_json(r["row_json"])
        if row.address in in_book:
            row.in_book = True
        out.append(row)
    wanted = store.meta_get(conn, "wanted_hash")
    return TraderPage(as_of_ms=ptr["as_of_ms"], refresh_id=ptr["refresh_id"], settings_hash=ptr["settings_hash"],
                      cohort_size=ptr["cohort_size"], total=int(total), rows=out,
                      stale_settings=bool(wanted and wanted != ptr["settings_hash"]))


def scout_presets() -> ScoutPresets:
    """Preset tabs + coin chips from the served board (contracts ScoutPresets):
    coin_counts = traders with the coin in their top 5; coins = the 6 chips
    with the most traders; hip3_count = traders with any HIP-3 coin in their
    top 5, the same predicate as the `preset=hip3` filter, so the tab count
    always equals the tab's total."""
    conn = _conn()
    ptr = store.pointer(conn)
    if ptr is None:
        return ScoutPresets()
    rid = ptr["refresh_id"]
    counts: Dict[str, int] = {}
    hip3 = total = 0
    for r in conn.execute("SELECT coins_csv FROM scout_rows WHERE refresh_id = ?", (rid,)).fetchall():
        total += 1
        coins = [c for c in (r["coins_csv"] or "").split(",") if c]
        hip3 += int(any(":" in c for c in coins))
        for c in coins:
            counts[c] = counts.get(c, 0) + 1
    order = sorted(counts, key=lambda c: (-counts[c], c))
    return ScoutPresets(refresh_id=rid, coins=order[:6], coin_counts=counts, hip3_count=hip3, total=total)


# ── trader file ───────────────────────────────────────────────────────────

def _queued_status(conn: Any) -> ScoutStatus:
    alive = R.scheduler_alive(conn)
    return ScoutStatus(refresh_id=None, state="running", stage="stats", done=0, total=1,
                       next_due_ms=store.meta_get(conn, "next_due_ms"),
                       error=None if alive else "scout serve is not running; the build is queued")


def scout_profile(address: str) -> Union[TraderProfile, ScoutStatus, None]:
    """None: invalid address, or a queued build that failed twice (no HL data).
    ScoutStatus: build queued for `serve` (api returns 202). An off-board
    wallet whose stats are older than one stage-B cycle is re-queued while
    the stored file keeps serving. Never builds in this process."""
    a = _addr(address)
    if a is None:
        return None
    conn = _conn()
    prof = rows.profile(conn, a)
    if prof is not None:
        st = store.stats_row(conn, a) or {}
        u = store.universe_row(conn, a)
        on_board = u is not None and u.get("source") != "ondemand"
        if not on_board and R.now_ms() - int(st.get("updated_ms") or 0) > C.STAGE_B_EVERY_S * 1000:
            store.request_build(conn, a, R.now_ms())
        return prof
    req = store.request_row(conn, a)
    if req is not None and int(req["attempts"]) >= R.MAX_REQUEST_ATTEMPTS:
        return None
    store.request_build(conn, a, R.now_ms())
    return _queued_status(conn)


def scout_fills(address: str, before_ms: Optional[int] = None, limit: int = 100) -> List[LeaderFillView]:
    a = _addr(address)
    if a is None:
        return []
    return rows.recent_fills(_conn(), a, before_ms, max(1, min(int(limit), 500)))


def _order_view(o: Dict[str, Any]) -> Dict[str, Any]:
    def f(k: str) -> Optional[float]:
        try:
            return float(o[k])
        except (KeyError, TypeError, ValueError):
            return None
    return {"coin": o.get("coin"), "side": o.get("side"), "px": f("limitPx"), "sz": f("sz"), "orig_sz": f("origSz"),
            "order_type": o.get("orderType"), "tif": o.get("tif"), "reduce_only": bool(o.get("reduceOnly")),
            "is_trigger": bool(o.get("isTrigger")), "trigger_px": f("triggerPx"),
            "trigger_condition": o.get("triggerCondition"), "is_position_tpsl": bool(o.get("isPositionTpsl")),
            "time_ms": o.get("timestamp"), "oid": o.get("oid")}


def scout_orders(address: str) -> List[Dict[str, Any]]:
    a = _addr(address)
    if a is None:
        return []
    with _orders_lock:
        hit = _orders_cache.get(a)
        if hit and time.monotonic() - hit[0] < C.ORDERS_TTL_S:
            return hit[1]
    raw = _default_venue().open_orders(a)
    if raw is None:
        raise ScoutReadError(f"open orders read failed for {a}")
    out = sorted((_order_view(o) for o in raw), key=lambda o: (-(o["time_ms"] or 0), str(o["coin"])))
    with _orders_lock:
        _orders_cache[a] = (time.monotonic(), out)
    return out


def scout_what_if(address: str, settings: Settings, sim_equity_usd: float,
                  override: Optional[LeaderOverride] = None) -> WhatIfResult:
    """The trader file's 'your copy' re-run: settings.for_leader(address)
    patched with `override`, on cached fills and candles only."""
    a = _addr(address)
    if a is None:
        raise ValueError(f"not a 0x address: {address!r}")
    if sim_equity_usd <= 0:
        raise ValueError("sim_equity_usd must be > 0")
    if not _what_if_lock.acquire(blocking=False):
        raise ScoutBusy("a what-if is already running")
    try:
        conn = _conn()
        inp = simstage.wallet_inputs(conn, a)
        if inp is None:
            raise LookupError(f"no Scout stats for {a} yet")
        eff = settings.for_leader(a)
        if override is not None:
            eff = eff.model_copy(update={k: v for k, v in override.model_dump().items() if v is not None})
        out = simstage.simulate(conn, simstage.CacheOnlyVenue(), inp["fills"], eff, float(sim_equity_usd),
                                inp["leader_equity"], inp["lev_by_coin"], inp["now_ms"],
                                _cfg["sizing"] or simstage.default_sizing(),
                                coin_max_lev=store.meta_get(conn, "coin_max_lev", {}) or {}, cache_only=True)
        u = store.universe_row(conn, a) or {}
        fl = out.fields
        score = TraderScore(
            address=a, display_name=u.get("display_name"), account_value_usd=float(u.get("account_value") or 0.0),
            pnl_30d_usd=float(u.get("pnl_30d") or 0.0), roi_30d_pct=float(u.get("roi_30d") or 0.0),
            pnl_all_time_usd=float(u.get("pnl_all") or 0.0), volume_30d_usd=float(u.get("vlm_30d") or 0.0),
            fills_30d=fl["fills_30d"], opens_per_day=fl["opens_per_day"], median_hold_h=fl["median_hold_h"],
            coins=fl["coins"], sim_return_pct=fl["sim_return_pct"], sim_max_drawdown_pct=fl["sim_max_drawdown_pct"],
            sim_liquidations=fl["sim_liquidations"], sim_copies=fl["sim_copies"],
            sim_skipped_min_order=fl["sim_skipped_min_order"], sim_fees_usd=fl["sim_fees_usd"], score=fl["score"],
            flags=fl["flags"], sim_copy_capacity_pct=fl["sim_copy_capacity_pct"], copy_fit=None,
            last_fill_ms=max((int(f["time_ms"]) for f in inp["fills"]), default=None))
        return WhatIfResult(score=score, sim_curve=out.curve)
    finally:
        _what_if_lock.release()


# ── refresh status / trigger ──────────────────────────────────────────────

def scout_status() -> ScoutStatus:
    conn = _conn()
    last = store.latest_refresh(conn)
    ok = store.last_ok_ms(conn)
    nxt = store.meta_get(conn, "next_due_ms")
    alive = R.scheduler_alive(conn)
    err = None
    if store.meta_get(conn, "refresh_requested") and not alive:
        err = "refresh requested, but scout serve is not running"
    if last is None:
        return ScoutStatus(refresh_id=None, state="idle", last_ok_ms=ok, next_due_ms=nxt,
                           error=err or (None if alive else "no refresh yet; start `python -m discovery.scout serve`"))
    state = last["state"]
    if state == "running" and R.now_ms() - int(last["heartbeat_ms"] or 0) > C.REFRESH_STALE_S * 1000:
        state, err = "failed", "refresh stopped heartbeating (process died)"
    if state == "done":
        state = "idle"
    return ScoutStatus(refresh_id=last["refresh_id"], state=state,
                       stage=last["stage"] if state == "running" else None,
                       done=int(last["done"] or 0), total=int(last["total"] or 0),
                       eta_s=last["eta_s"] if state == "running" else None,
                       last_ok_ms=ok, next_due_ms=nxt, error=err or (last["error"] if state == "failed" else None))


def scout_refresh() -> ScoutStatus:
    """Ask `serve` for a full A+B+C refresh on its next tick (<= 10 s).
    ScoutBusy when one is running or already queued."""
    conn = _conn()
    st = scout_status()
    if st.state == "running":
        raise ScoutBusy(f"scout refresh {(st.refresh_id or '')[:8]} is running ({st.stage})")
    if store.meta_get(conn, "refresh_requested"):
        raise ScoutBusy("a scout refresh is already queued")
    store.meta_set(conn, {"refresh_requested": R.now_ms()})
    return scout_status()


def serve(settings_provider: Callable[[], Settings], sim_equity_provider: Optional[Callable[[], float]] = None,
          stop: Optional[threading.Event] = None, tick_s: float = C.SCHEDULER_TICK_S) -> None:
    use_background_priority()
    run_scheduler(settings_provider, venue=_default_venue(), sim_equity_provider=sim_equity_provider,
                  stop=stop, sizing=_cfg["sizing"], tick_s=tick_s, db_path=_cfg["db_path"])
