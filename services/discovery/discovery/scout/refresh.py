"""The Scout refresh pipeline and its scheduler (spec 7.2). Single writer.

    A  leaderboard -> scout_universe                       every 15 min, 0 /info weight
    B  per-wallet stats -> scout_stats                     every 60 min, budgeted
    C  copy-sim at the saved settings -> scout_sim         after B, and when settings change
    publish: Copy Fit over the cohort -> scout_rows (new refresh_id) -> pointer switch

One refresh at a time across every process: `store.try_begin_refresh`
claims the slot with BEGIN IMMEDIATE; a second claimant gets ScoutBusy.

Settings: the board is scored at `settings_hash(settings, sim_equity)`.
When the hash changes, the old board keeps serving (TraderPage.stale_settings)
until stage C has simulated every board wallet at the new hash; only then
is the board republished at the new hash. A first-ever build, or an explicit
allow_partial (the live eval), publishes whatever C finished.

Progress: scout_refresh row (stage, done/total, eta, heartbeat) and
/tmp/scout-refresh/progress.log, one line per wallet, computed (not
estimated by eye): rate = done / elapsed, eta = remaining / rate.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from contracts.models import Settings
from contracts.venue import Venue

from . import config as C
from . import rows, simstage, stats, store, universe

logger = logging.getLogger(__name__)

MAX_REQUEST_ATTEMPTS = 2


class ScoutBusy(RuntimeError):
    """A refresh is already running (or queued). The api maps this to 409."""


def settings_hash(settings: Settings, sim_equity: float) -> str:
    """Everything that changes a sim result: Settings minus the fields the
    sim never reads (enabled, dry_run, leaders, contract_version), plus the
    simulated copier's equity."""
    d = settings.model_dump(mode="json", exclude={"enabled", "dry_run", "leaders", "contract_version"})
    d["sim_equity_usd"] = round(float(sim_equity), 6)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def now_ms() -> int:
    return int(time.time() * 1000)


def _had_real_liquidation(conn: Any, address: str) -> bool:
    """A departing wallet's last known (not sim) liquidation state, from its
    last stage-B stats (user_consensus P1 #7: classify departures, not just
    count them). False when there are no stats at all, never an error."""
    st = store.stats_row(conn, address)
    if not st or not st.get("stats_json"):
        return False
    try:
        return bool((json.loads(st["stats_json"]) or {}).get("liquidations_30d"))
    except (ValueError, TypeError):
        return False


def eta_s(done: int, total: int, elapsed_s: float) -> Optional[float]:
    if done <= 0 or total <= 0 or elapsed_s <= 0:
        return None
    return max(0, total - done) * elapsed_s / done


class Progress:
    """Writes stage progress to scout_refresh and appends to the progress log."""

    def __init__(self, conn: Any, refresh_id: str, log_path: Optional[Path] = None) -> None:
        self.conn, self.refresh_id = conn, refresh_id
        self.log_path = log_path or C.progress_log_path()
        self.stage = "leaderboard"
        self.t0 = time.monotonic()
        self.errors = 0
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def begin(self, stage: str, total: int) -> None:
        self.stage, self.t0 = stage, time.monotonic()
        store.update_refresh(self.conn, self.refresh_id, stage=stage, done=0, total=total, eta_s=None,
                             heartbeat_ms=now_ms())
        self.log(f"stage {stage} start, {total} to do")

    def step(self, done: int, total: int) -> None:
        el = time.monotonic() - self.t0
        eta = eta_s(done, total, el)
        store.update_refresh(self.conn, self.refresh_id, done=done, total=total, eta_s=eta, heartbeat_ms=now_ms())
        pct = done / total * 100.0 if total else 100.0
        rate = done / el if el > 0 else 0.0
        self.log(f"stage {self.stage} {pct:5.1f}% eta {_fmt_s(eta)} | {done}/{total} rate {rate:.2f}/s "
                 f"errors {self.errors}")

    def log(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} scout-refresh {self.refresh_id[:8]} {msg}"
        logger.info(line)
        try:
            with open(self.log_path, "a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _fmt_s(s: Optional[float]) -> str:
    if s is None:
        return "?"
    s = int(s)
    return f"{s // 60}m{s % 60:02d}s"


@dataclass
class RefreshOptions:
    stages: Sequence[str] = ("A", "B", "C")
    limit_b: Optional[int] = None
    limit_c: Optional[int] = None
    max_weight_b: float = C.STAGE_B_MAX_WEIGHT
    max_s_b: float = C.STAGE_B_MAX_S
    max_weight_c: float = C.STAGE_C_MAX_WEIGHT
    max_s_c: float = C.STAGE_C_MAX_S
    allow_partial: bool = False
    only: Optional[List[str]] = None       # restrict B/C to these addresses (on-demand)
    kind: str = "scheduled"


@dataclass
class RefreshReport:
    refresh_id: str
    universe: int = 0
    stats_done: int = 0
    stats_failed: int = 0
    stats_deferred: int = 0
    sims_done: int = 0
    sims_failed: int = 0
    published: bool = False
    cohort: int = 0
    weight_b: float = 0.0
    weight_c: float = 0.0
    timings_s: Dict[str, float] = field(default_factory=dict)


def run_refresh(venue: Venue, settings: Settings, sim_equity: float, opts: Optional[RefreshOptions] = None,
                sizing: Any = None, db_path: Optional[Path] = None) -> RefreshReport:
    """Synchronous. Raises ScoutBusy when another refresh holds the slot."""
    opts = opts or RefreshOptions()
    conn = store.connect(db_path)
    rid = uuid.uuid4().hex
    blocking = store.try_begin_refresh(conn, rid, now_ms(), opts.kind)
    if blocking is not None:
        raise ScoutBusy(f"scout refresh {blocking['refresh_id'][:8]} is running (stage {blocking['stage']})")
    rep = RefreshReport(refresh_id=rid)
    prog = Progress(conn, rid)
    try:
        _run(conn, venue, settings, sim_equity, opts, sizing, rep, prog)
        store.update_refresh(conn, rid, state="done", finished_ms=now_ms(), heartbeat_ms=now_ms())
        prog.log(f"done: universe={rep.universe} stats={rep.stats_done} (failed {rep.stats_failed}, "
                 f"deferred {rep.stats_deferred}) sims={rep.sims_done} published={rep.published} "
                 f"cohort={rep.cohort} weight B={rep.weight_b:.0f} C={rep.weight_c:.0f}")
    except Exception as exc:
        store.update_refresh(conn, rid, state="failed", finished_ms=now_ms(), error=f"{type(exc).__name__}: {exc}")
        prog.log(f"failed: {exc}")
        raise
    return rep


def _run(conn: Any, venue: Venue, settings: Settings, sim_equity: float, opts: RefreshOptions, sizing: Any,
         rep: RefreshReport, prog: Progress) -> None:
    book = list(settings.leaders)
    want = settings_hash(settings, sim_equity)
    store.meta_set(conn, {"wanted_hash": want})

    if "A" in opts.stages:
        t = time.monotonic()
        prog.begin("leaderboard", 1)
        prev = {r["address"]: r for r in store.universe(conn)}
        sel = universe.run_stage_a(venue, now_ms(), book)
        if sel is not None:
            new_addrs = {r["address"] for r in sel}
            dropped = [dict(r, had_liquidation=_had_real_liquidation(conn, a))
                      for a, r in prev.items() if a not in new_addrs]
            if dropped:
                store.record_departures(conn, dropped, now_ms())
            store.replace_universe(conn, sel, keep_sources=("ondemand",))
            store.meta_set(conn, {"last_a_ms": now_ms()})
        elif not store.universe(conn):
            raise RuntimeError("leaderboard read failed and there is no previous universe")
        prog.step(1, 1)
        rep.timings_s["A"] = round(time.monotonic() - t, 2)
    addrs = opts.only if opts.only is not None else [u["address"] for u in store.universe(conn)]
    rep.universe = len(addrs)

    if "B" in opts.stages:
        t = time.monotonic()
        budget = stats.Budget(opts.max_weight_b, opts.max_s_b)
        n = len(addrs) if opts.limit_b is None else min(len(addrs), opts.limit_b)
        prog.begin("stats", n)
        res = stats.run_stage_b(conn, venue, addrs, now_ms(), budget, book=book,
                                requested=opts.only or (), limit=opts.limit_b, progress=prog.step)
        prog.errors += len(res.failed)
        rep.stats_done, rep.stats_failed, rep.stats_deferred = len(res.done), len(res.failed), len(res.deferred)
        rep.weight_b = res.weight
        if opts.only is None and opts.limit_b is None:
            store.meta_set(conn, {"last_b_ms": now_ms()})
        rep.timings_s["B"] = round(time.monotonic() - t, 2)

    publish_hash = store.meta_get(conn, "sim_hash")
    publish_eq = store.meta_get(conn, "sim_equity", sim_equity)
    if "C" in opts.stages:
        t = time.monotonic()
        budget = stats.Budget(opts.max_weight_c, opts.max_s_c)
        prog.begin("sim", len(addrs) if opts.limit_c is None else min(len(addrs), opts.limit_c))
        res_c = simstage.run_stage_c(conn, venue, addrs, settings, sim_equity, want, budget,
                                     sizing or simstage.default_sizing(), limit=opts.limit_c, progress=prog.step)
        prog.errors += len(res_c.failed)
        rep.sims_done, rep.sims_failed, rep.weight_c = len(res_c.done), len(res_c.failed), res_c.weight
        complete = not res_c.deferred and not res_c.failed
        if opts.only is None and (complete or publish_hash is None or opts.allow_partial):
            publish_hash, publish_eq = want, sim_equity
            store.meta_set(conn, {"sim_hash": want, "sim_equity": sim_equity})
        rep.timings_s["C"] = round(time.monotonic() - t, 2)

    if opts.only is None:
        t = time.monotonic()
        prog.begin("sim", 1)
        if publish_hash is None:          # B ran, C never has: publish unsimulated rows at the wanted hash
            publish_hash, publish_eq = want, sim_equity
        rep.cohort = rows.build(conn, rep.refresh_id, publish_hash, float(publish_eq), now_ms())
        rep.published = True
        prog.step(1, 1)
        rep.timings_s["publish"] = round(time.monotonic() - t, 2)


# ── scheduler (`python -m discovery.scout serve`) ─────────────────────────

def scheduler_alive(conn: Any, at_ms: Optional[int] = None) -> bool:
    hb = store.meta_get(conn, "scheduler_heartbeat_ms")
    return hb is not None and (at_ms or now_ms()) - int(hb) <= C.SCHEDULER_ALIVE_S * 1000


@dataclass
class Plan:
    stages: List[str]
    reason: str


def plan(conn: Any, want_hash: str, at_ms: int) -> Optional[Plan]:
    """What the scheduler should run now, if anything. Pure over scout_meta."""
    if store.meta_get(conn, "refresh_requested"):
        return Plan(["A", "B", "C"], "requested")
    last_a = int(store.meta_get(conn, "last_a_ms", 0) or 0)
    last_b = int(store.meta_get(conn, "last_b_ms", 0) or 0)
    if at_ms - last_b >= C.STAGE_B_EVERY_S * 1000:
        return Plan(["A", "B", "C"], "stats due")
    if at_ms - last_a >= C.STAGE_A_EVERY_S * 1000:
        return Plan(["A"], "leaderboard due")
    if store.meta_get(conn, "sim_hash") != want_hash:
        return Plan(["C"], "settings changed")
    return None


def next_due_ms(conn: Any) -> int:
    last_a = int(store.meta_get(conn, "last_a_ms", 0) or 0)
    last_b = int(store.meta_get(conn, "last_b_ms", 0) or 0)
    return min(last_a + int(C.STAGE_A_EVERY_S * 1000), last_b + int(C.STAGE_B_EVERY_S * 1000))


def tick(venue: Venue, settings: Settings, sim_equity: float, sizing: Any = None,
         db_path: Optional[Path] = None) -> Optional[RefreshReport]:
    """One scheduler step: heartbeat, on-demand requests, then the due stages."""
    conn = store.connect(db_path)
    t = now_ms()
    want = settings_hash(settings, sim_equity)
    store.meta_set(conn, {"scheduler_heartbeat_ms": t, "wanted_hash": want})
    for a in store.pending_requests(conn, MAX_REQUEST_ATTEMPTS):
        try:
            run_refresh(venue, settings, sim_equity, RefreshOptions(stages=("B", "C"), only=[a], kind="ondemand"),
                        sizing, db_path)
            ok = store.stats_row(conn, a)
            store.finish_request(conn, a, None if ok and ok.get("updated_ms") and not ok.get("fail_count")
                                 else (ok or {}).get("last_error") or "no stats")
        except ScoutBusy:
            return None
        except Exception as exc:
            store.finish_request(conn, a, f"{type(exc).__name__}: {exc}")
    p = plan(conn, want, t)
    rep = None
    if p is not None:
        logger.info("scout scheduler: running %s (%s)", "".join(p.stages), p.reason)
        try:
            if p.reason == "requested":
                store.meta_set(conn, {"refresh_requested": None})
            rep = run_refresh(venue, settings, sim_equity, RefreshOptions(stages=p.stages, kind=p.reason),
                              sizing, db_path)
        except ScoutBusy:
            pass
        except Exception:
            logger.exception("scout scheduler: refresh failed")
            store.meta_set(conn, {"last_b_ms": t} if "B" in p.stages else {"last_a_ms": t})  # no hot retry loop
    store.meta_set(conn, {"next_due_ms": next_due_ms(conn), "scheduler_heartbeat_ms": now_ms()})
    return rep


def run_scheduler(settings_provider: Callable[[], Settings], venue: Optional[Venue] = None,
                  sim_equity_provider: Optional[Callable[[], float]] = None,
                  stop: Optional[threading.Event] = None, sizing: Any = None,
                  tick_s: float = C.SCHEDULER_TICK_S, db_path: Optional[Path] = None) -> None:
    """Blocking loop. settings_provider() is read every tick, so a settings
    save (book change, sizing change) is picked up within one tick."""
    stop = stop or threading.Event()
    if venue is None:
        from .public import _default_venue
        venue = _default_venue()
    while not stop.is_set():
        try:
            eq = float(sim_equity_provider()) if sim_equity_provider else C.DEFAULT_SIM_EQUITY_USD
            tick(venue, settings_provider(), eq, sizing, db_path)
        except Exception:
            logger.exception("scout scheduler: tick failed")
        stop.wait(tick_s)
