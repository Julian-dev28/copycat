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

from contracts.models import ScoutSimTerms, Settings
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
    simulated copier's equity. Used only for terms.use_live_settings=True
    (the pre-v16 board): unchanged so that mode's cache is untouched by
    ScoutSimTerms shipping."""
    d = settings.model_dump(mode="json", exclude={"enabled", "dry_run", "leaders", "contract_version"})
    d["sim_equity_usd"] = round(float(sim_equity), 6)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def terms_hash(terms: ScoutSimTerms) -> str:
    """Hash of the sim terms a board was built at, when NOT using live settings.
    use_live_settings is excluded: it never reaches the sim (effective_hash below
    picks settings_hash or terms_hash entirely, it does not mix the two), so two
    terms that differ only in that flag must not collide by accident of a stray
    field, nor matter here since the flag already decided which hash function ran."""
    d = terms.model_dump(mode="json", exclude={"use_live_settings"})
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def effective_hash(terms: ScoutSimTerms, settings: Settings, live_sim_equity: float) -> str:
    """The board's wanted hash: the pre-v16 Settings-based hash when the operator
    chose to sim at their own live settings, else the sim-terms hash. These are
    deliberately different hash spaces (a terms hash never equals a settings hash
    by construction) so switching use_live_settings never serves stale rows under
    the wrong terms."""
    return settings_hash(settings, live_sim_equity) if terms.use_live_settings else terms_hash(terms)


def effective_sim_equity(terms: ScoutSimTerms, live_sim_equity: float) -> float:
    return live_sim_equity if terms.use_live_settings else terms.sim_equity_usd


def effective_settings_for_leader(terms: ScoutSimTerms, settings: Settings) -> Callable[[str], Settings]:
    """Per-wallet effective Settings for the copy-sim: Settings.for_leader(wallet)
    under use_live_settings, else the SAME terms-derived Settings for every
    wallet (ScoutSimTerms has no per-leader overrides -- it is one sheet for the
    whole board)."""
    if terms.use_live_settings:
        return settings.for_leader
    eff = terms.to_settings()
    return lambda _address: eff


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
    """None until there is enough signal to be honest (indexing tightening):
    at least C.ETA_MIN_DONE wallets done, OR C.ETA_MIN_FRAC of the total,
    whichever comes first. A 7/301 pass (2.3%, 7 done) used to show
    "eta 394m02s" from the first few wallets' rate -- a number dressed up
    as a fact. Below the gate, the web badge shows progress with no time."""
    if done <= 0 or total <= 0 or elapsed_s <= 0:
        return None
    if done < C.ETA_MIN_DONE and done < total * C.ETA_MIN_FRAC:
        return None
    return max(0, total - done) * elapsed_s / done


class Progress:
    """Writes stage progress to scout_refresh and appends to the progress log."""

    def __init__(self, conn: Any, refresh_id: str, log_path: Optional[Path] = None,
                 on_beat: Optional[Callable[[], None]] = None) -> None:
        self.conn, self.refresh_id = conn, refresh_id
        self.log_path = log_path or C.progress_log_path()
        self.on_beat = on_beat
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
        self._beat()
        self.log(f"stage {stage} start, {total} to do")

    def step(self, done: int, total: int) -> None:
        el = time.monotonic() - self.t0
        eta = eta_s(done, total, el)
        store.update_refresh(self.conn, self.refresh_id, done=done, total=total, eta_s=eta, heartbeat_ms=now_ms())
        self._beat()
        pct = done / total * 100.0 if total else 100.0
        rate = done / el if el > 0 else 0.0
        self.log(f"stage {self.stage} {pct:5.1f}% eta {_fmt_s(eta)} | {done}/{total} rate {rate:.2f}/s "
                 f"errors {self.errors}")

    def _beat(self) -> None:
        if self.on_beat is not None:
            try:
                self.on_beat()
            except Exception:
                logger.debug("progress beat failed", exc_info=True)

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
    # Called at every progress step. The scheduler passes its own heartbeat
    # writer, so a 20-minute refresh keeps `scheduler_alive` true while it runs.
    on_beat: Optional[Callable[[], None]] = None


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
                sizing: Any = None, db_path: Optional[Path] = None,
                terms: Optional[ScoutSimTerms] = None) -> RefreshReport:
    """Synchronous. Raises ScoutBusy when another refresh holds the slot.
    `terms`: the Scout board's sim terms; None (every pre-v16 caller) keeps the
    old behavior, simming at Settings.for_leader + `sim_equity` as if
    use_live_settings were set."""
    opts = opts or RefreshOptions()
    terms = terms if terms is not None else ScoutSimTerms(use_live_settings=True)
    conn = store.connect(db_path)
    rid = uuid.uuid4().hex
    blocking = store.try_begin_refresh(conn, rid, now_ms(), opts.kind)
    if blocking is not None:
        raise ScoutBusy(f"scout refresh {blocking['refresh_id'][:8]} is running (stage {blocking['stage']})")
    rep = RefreshReport(refresh_id=rid)
    prog = Progress(conn, rid, on_beat=opts.on_beat)
    try:
        _run(conn, venue, settings, sim_equity, opts, sizing, rep, prog, terms)
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
         rep: RefreshReport, prog: Progress, terms: ScoutSimTerms) -> None:
    book = list(settings.leaders)
    custom = store.custom_addresses(conn)
    want = effective_hash(terms, settings, sim_equity)
    store.meta_set(conn, {"wanted_hash": want})

    if "A" in opts.stages:
        t = time.monotonic()
        prog.begin("leaderboard", 1)
        prev = {r["address"]: r for r in store.universe(conn, ("lb", "book"))}
        sel = universe.run_stage_a(venue, now_ms(), book, custom)
        if sel is not None:
            new_addrs = {r["address"] for r in sel}
            dropped = [dict(r, had_liquidation=_had_real_liquidation(conn, a))
                      for a, r in prev.items() if a not in new_addrs]
            if dropped:
                store.record_departures(conn, dropped, now_ms())
            store.replace_universe(conn, sel, keep_sources=("ondemand", "custom"))
            store.meta_set(conn, {"last_a_ms": now_ms()})
        elif not store.universe(conn):
            raise RuntimeError("leaderboard read failed and there is no previous universe")
        prog.step(1, 1)
        rep.timings_s["A"] = round(time.monotonic() - t, 2)
    if opts.only is not None:
        addrs = list(opts.only)
    else:
        # every board-source universe row, plus hand-added wallets the leaderboard has never
        # listed (no universe row yet: stage B creates it from the wallet's own portfolio)
        addrs = [u["address"] for u in store.universe(conn)]
        addrs += [a for a in custom if a not in set(addrs)]
    rep.universe = len(addrs)

    if "B" in opts.stages:
        t = time.monotonic()
        budget = stats.Budget(opts.max_weight_b, opts.max_s_b)
        n = len(addrs) if opts.limit_b is None else min(len(addrs), opts.limit_b)
        prog.begin("stats", n)
        res = stats.run_stage_b(conn, venue, addrs, now_ms(), budget, book=book,
                                requested=opts.only or (), limit=opts.limit_b, progress=prog.step, custom=custom)
        prog.errors += len(res.failed)
        rep.stats_done, rep.stats_failed, rep.stats_deferred = len(res.done), len(res.failed), len(res.deferred)
        rep.weight_b = res.weight
        if opts.only is None and opts.limit_b is None:
            store.meta_set(conn, {"last_b_ms": now_ms()})
        rep.timings_s["B"] = round(time.monotonic() - t, 2)

    publish_hash = store.meta_get(conn, "sim_hash")
    publish_eq = store.meta_get(conn, "sim_equity", sim_equity)
    eff_equity = effective_sim_equity(terms, sim_equity)
    if "C" in opts.stages:
        t = time.monotonic()
        budget = stats.Budget(opts.max_weight_c, opts.max_s_c)
        prog.begin("sim", len(addrs) if opts.limit_c is None else min(len(addrs), opts.limit_c))
        res_c = simstage.run_stage_c(conn, venue, addrs, effective_settings_for_leader(terms, settings), eff_equity,
                                     want, budget, sizing or simstage.default_sizing(), limit=opts.limit_c,
                                     progress=prog.step, allow_cache_only=not terms.use_live_settings)
        prog.errors += len(res_c.failed)
        rep.sims_done, rep.sims_failed, rep.weight_c = len(res_c.done), len(res_c.failed), res_c.weight
        complete = not res_c.deferred and not res_c.failed
        if opts.only is None and (complete or publish_hash is None or opts.allow_partial):
            publish_hash, publish_eq = want, eff_equity
            store.meta_set(conn, {"sim_hash": want, "sim_equity": eff_equity})
        rep.timings_s["C"] = round(time.monotonic() - t, 2)

    if opts.only is None:
        t = time.monotonic()
        prog.begin("sim", 1)
        if publish_hash is None:          # B ran, C never has: publish unsimulated rows at the wanted hash
            publish_hash, publish_eq = want, eff_equity
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


def _stats_error(conn: Any, address: str) -> Optional[str]:
    """None when the wallet's stage-B stats are good, else why not."""
    ok = store.stats_row(conn, address)
    if ok and ok.get("updated_ms") and not ok.get("fail_count"):
        return None
    return (ok or {}).get("last_error") or "no stats"


def build_one(conn: Any, venue: Venue, settings: Settings, sim_equity: float, sizing: Any,
              address: str, book: Sequence[str], custom: Sequence[str],
              terms: Optional[ScoutSimTerms] = None) -> Optional[str]:
    """Stage B then C for one wallet without claiming the refresh slot or writing a
    progress row: the nested path a running refresh uses to serve an on-demand request
    between two of its own wallets. Returns the stats error, None when built."""
    terms = terms if terms is not None else ScoutSimTerms(use_live_settings=True)
    stats.run_stage_b(conn, venue, [address], now_ms(), stats.Budget(C.STAGE_B_MAX_WEIGHT, C.STAGE_B_MAX_S),
                      book=book, requested=[address], custom=custom)
    err = _stats_error(conn, address)
    if err is None:
        eq = effective_sim_equity(terms, sim_equity)
        simstage.run_stage_c(conn, venue, [address], effective_settings_for_leader(terms, settings), eq,
                             effective_hash(terms, settings, sim_equity),
                             stats.Budget(C.STAGE_C_MAX_WEIGHT, C.STAGE_C_MAX_S), sizing or simstage.default_sizing(),
                             allow_cache_only=not terms.use_live_settings)
    return err


def republish(conn: Any, settings: Settings, sim_equity: float, terms: Optional[ScoutSimTerms] = None) -> int:
    """Rebuild the served board from what is stored (no HL call) so a wallet built just now
    shows up at once instead of at the end of the next full refresh. Uses the served
    build's settings hash and equity so rows stay comparable; before the first build
    (fresh database, the first full refresh still running) it publishes a first board
    at the wanted hash with whatever has stats, which the full refresh then replaces.
    Caught by evals/custom_wallet_check.sh: a wallet added during the very first refresh
    was built but had no board to appear on for the refresh's whole run."""
    ptr = store.pointer(conn)
    if ptr is None:
        terms = terms if terms is not None else ScoutSimTerms(use_live_settings=True)
        h, eq = effective_hash(terms, settings, sim_equity), effective_sim_equity(terms, sim_equity)
    else:
        h, eq = ptr["settings_hash"], float(ptr.get("sim_equity") or sim_equity)
    return rows.build(conn, uuid.uuid4().hex, h, eq, now_ms())


def service_requests(conn: Any, venue: Venue, settings: Settings, sim_equity: float, sizing: Any,
                     db_path: Optional[Path], on_beat: Optional[Callable[[], None]] = None,
                     nested: bool = False, terms: Optional[ScoutSimTerms] = None) -> None:
    """Build every queued on-demand wallet (trader files opened for wallets Scout does not
    track, and custom wallets just added). `nested` = called from inside a running
    refresh's progress beat: build without the slot. A custom wallet gets the board
    republished as soon as it is built."""
    book = list(settings.leaders)
    custom = store.custom_addresses(conn)
    for a in store.pending_requests(conn, MAX_REQUEST_ATTEMPTS):
        if store.request_row(conn, a) is None:        # served meanwhile by a nested beat
            continue
        t0 = time.monotonic()
        try:
            if nested:
                err = build_one(conn, venue, settings, sim_equity, sizing, a, book, custom, terms)
            else:
                run_refresh(venue, settings, sim_equity,
                            RefreshOptions(stages=("B", "C"), only=[a], kind="ondemand", on_beat=on_beat),
                            sizing, db_path, terms)
                err = _stats_error(conn, a)
            store.finish_request(conn, a, err)
            published = None
            if err is None and a in custom:
                published = republish(conn, settings, sim_equity, terms)
            logger.info("scout on-demand: %s %s in %.0fs%s%s", a, "failed" if err else "built",
                        time.monotonic() - t0, " mid-refresh" if nested else "",
                        f", board republished ({published} rows)" if published is not None else "")
        except ScoutBusy:
            return
        except Exception as exc:
            logger.warning("scout on-demand build of %s failed: %s", a, exc)
            store.finish_request(conn, a, f"{type(exc).__name__}: {exc}")


def tick(venue: Venue, settings: Settings, sim_equity: float, sizing: Any = None,
         db_path: Optional[Path] = None, terms: Optional[ScoutSimTerms] = None) -> Optional[RefreshReport]:
    """One scheduler step: heartbeat, on-demand requests, then the due stages.
    `terms` is read fresh every tick (like `settings`), so a PUT /api/scout/sim-terms
    from the api is picked up within one tick: `wanted_hash` changes at once (the
    board flips to stale_settings immediately) and `plan()` schedules a stage-C
    re-sim on this same tick or the next."""
    terms = terms if terms is not None else ScoutSimTerms(use_live_settings=True)
    conn = store.connect(db_path)
    t = now_ms()
    want = effective_hash(terms, settings, sim_equity)
    store.meta_set(conn, {"scheduler_heartbeat_ms": t, "wanted_hash": want})
    draining = {"on": False}

    def beat() -> None:
        # Before this, the heartbeat was written only here and after the stages
        # ran, so every refresh longer than SCHEDULER_ALIVE_S (90s; a full one
        # takes 20 minutes) made health report scout `alive: False` and the
        # status say "scout serve is not running" while it was running.
        store.meta_set(conn, {"scheduler_heartbeat_ms": now_ms()})
        # A trader file or custom wallet requested during that refresh used to wait for
        # it to finish (45 minutes live) behind "usually under a minute". The refresh
        # now serves the queue between two of its own wallets. `draining` guards the
        # beat the nested build's own stage calls would otherwise re-enter.
        if draining["on"]:
            return
        draining["on"] = True
        try:
            service_requests(conn, venue, settings, sim_equity, sizing, db_path, nested=True, terms=terms)
        finally:
            draining["on"] = False

    # The top-level service IS the drain: its own mini refresh beats too, and without
    # the guard that beat re-served the request it was serving (every on-demand wallet
    # was built twice: "built in 3s mid-refresh" then "built in 6s", live 2026-10-14).
    draining["on"] = True
    try:
        service_requests(conn, venue, settings, sim_equity, sizing, db_path, on_beat=beat, terms=terms)
    finally:
        draining["on"] = False
    p = plan(conn, want, t)
    rep = None
    if p is not None:
        logger.info("scout scheduler: running %s (%s)", "".join(p.stages), p.reason)
        try:
            if p.reason == "requested":
                store.meta_set(conn, {"refresh_requested": None})
            rep = run_refresh(venue, settings, sim_equity,
                              RefreshOptions(stages=p.stages, kind=p.reason, on_beat=beat), sizing, db_path, terms)
        except ScoutBusy as exc:
            logger.debug("scout scheduler: %s due but %s", "".join(p.stages), exc)
        except Exception:
            logger.exception("scout scheduler: refresh failed")
            store.meta_set(conn, {"last_b_ms": t} if "B" in p.stages else {"last_a_ms": t})  # no hot retry loop
    store.meta_set(conn, {"next_due_ms": next_due_ms(conn), "scheduler_heartbeat_ms": now_ms()})
    return rep


def on_scheduler_start(conn: Any) -> int:
    """`scout serve` is the only process that runs refreshes, so a `running` row at
    its start belongs to the process that was killed (a restart mid-refresh). Until
    this, that row held the slot for REFRESH_STALE_S (15 min): every tick logged
    "running ABC (stats due)" and did nothing (live 2026-10-14 22:14 to 22:27)."""
    n = store.fail_running_refreshes(conn, now_ms(), "scout restarted")
    if n:
        logger.info("scout scheduler: %d refresh(es) left running by the previous process marked failed", n)
    return n


def run_scheduler(settings_provider: Callable[[], Settings], venue: Optional[Venue] = None,
                  sim_equity_provider: Optional[Callable[[], float]] = None,
                  stop: Optional[threading.Event] = None, sizing: Any = None,
                  tick_s: float = C.SCHEDULER_TICK_S, db_path: Optional[Path] = None,
                  terms_provider: Optional[Callable[[], ScoutSimTerms]] = None) -> None:
    """Blocking loop. settings_provider() is read every tick, so a settings
    save (book change, sizing change) is picked up within one tick.
    terms_provider() is read every tick the same way: a PUT /api/scout/sim-terms
    is picked up within one SCHEDULER_TICK_S (10s), no restart."""
    stop = stop or threading.Event()
    if venue is None:
        from .public import _default_venue
        venue = _default_venue()
    on_scheduler_start(store.connect(db_path))
    while not stop.is_set():
        try:
            eq = float(sim_equity_provider()) if sim_equity_provider else C.DEFAULT_SIM_EQUITY_USD
            terms = terms_provider() if terms_provider else None
            tick(venue, settings_provider(), eq, sizing, db_path, terms)
        except Exception:
            logger.exception("scout scheduler: tick failed")
        stop.wait(tick_s)
