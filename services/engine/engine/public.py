"""engine.public: the engine's entire contract surface for other services.

`services/api` imports exactly these four names and nothing else from this
package (per docs/ARCHITECTURE.md, "contracts at the boundary" -- no
service reaches into another's internals):

  run_cycle(venue, now_ms=None) -> dict      one cycle, returns a summary
  run_forever(venue, max_cycles=None)        the worker loop
  status() -> EngineStatus                   reads SQLite only, no venue
  events(limit, since_ms) -> list[EngineEvent]

Paths all come from `$COPYCAT_DATA_DIR` (default `./data`):
  engine.db       SQLite state (services/engine/engine/state.py)
  events.jsonl    the append-only event log (services/engine/engine/events.py)
  settings.json   written by the api, read-only here (services/engine/engine/settings_io.py)
  close_all.flag  written by the api (POST /api/engine/close-all), deleted here
                  once every copy is closed
  engine.lock     flock held by the one running worker (run_forever)
  stop/<address>.flag  written by the api (POST /api/wallets/{address}/stop),
                  JSON {close_positions}; deleted here once that wallet is stopped

Also `preview_wallet(address, request, settings, venue=None) -> WalletPreview`
for the Trade ticket (POST /api/wallets/{address}/preview): read-only HL
reads, sized by the same `engine.sizing.plan_allocation` the engine uses.
"""
from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import re
import signal
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from contracts.models import (
    EngineEvent,
    EngineStatus,
    Settings,
    SizingMode,
    WalletCopyRequest,
    WalletPreview,
    WalletPreviewSlice,
    norm_addr,
)
from contracts.venue import Venue

from . import account as account_mod
from . import core, settings_io, sizing, switch
from . import events as events_mod
from .state import EngineState

logger = logging.getLogger(__name__)

_STATUS_KV_KEY = "last_status"
_MIN_RUNNING_STALENESS_MS = 30_000


def _data_dir() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data"))


def _db_path(address: Optional[str] = None) -> Path:
    """Per-account state: engine-<address>.db (engine.account). Default: the
    account the engine trades right now."""
    return account_mod.db_path(address if address is not None else account_mod.resolve_our_address())


def _events_path() -> Path:
    return _data_dir() / "events.jsonl"


def _settings_path() -> Path:
    return _data_dir() / "settings.json"


CLOSE_ALL_FLAG = "close_all.flag"
LOCK_FILE = "engine.lock"


def _close_all_path() -> Path:
    return _data_dir() / CLOSE_ALL_FLAG


STOP_DIR = "stop"
_ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")


def _stop_dir() -> Path:
    return _data_dir() / STOP_DIR


def read_stops() -> Dict[str, bool]:
    """`data/stop/<address>.flag` -> {address: close_positions}. A flag whose
    JSON does not parse is read as close_positions true (the contract
    default; the api writes atomically, so this is a hand-edited file).
    Names that are not a 0x address are ignored."""
    out: Dict[str, bool] = {}
    d = _stop_dir()
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.flag")):
        addr = norm_addr(f.stem)
        if not _ADDR_RE.match(addr):
            continue
        try:
            raw = json.loads(f.read_text() or "{}")
            out[addr] = bool(raw.get("close_positions", True)) if isinstance(raw, dict) else True
        except (OSError, ValueError):
            out[addr] = True
    return out


def _clear_stop(addr: str) -> None:
    try:
        (_stop_dir() / f"{addr}.flag").unlink()
    except FileNotFoundError:
        pass


class EngineAlreadyRunning(RuntimeError):
    """Another worker holds `data/engine.lock`. Two workers on one data dir
    would each diff the same leaders and both place the same orders."""


def run_cycle(venue: Venue, now_ms: Optional[int] = None) -> dict:
    """Run exactly one cycle against `venue` and return a summary dict
    (opened/added/reduced/closed/skipped + leaders_ok/leaders_total +
    equity_usd/day_pnl_usd/halted_reason). Reloads settings.json, persists
    an `EngineStatus` snapshot to SQLite (so `status()` can read it from a
    fresh process with no venue), appends any `EngineEvent`s to
    events.jsonl, and logs one line.

    `now_ms` defaults to the real clock; tests pass a fixed value.
    """
    t0 = time.monotonic()
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    # Written as they happen, not batched at the end: if the cycle raises
    # after an order went through, the open/close event must still be in
    # the log, or the feed would disagree with the exchange.
    def log_event(e: EngineEvent) -> None:
        events_mod.append_event(_events_path(), e)

    # Re-resolved every cycle: activating another account in the vault switches
    # the engine at the next cycle, onto that account's own state db.
    our_address = account_mod.resolve_our_address()
    switch.note_account(data_dir, our_address, now_ms, log_event)
    if not our_address:
        return _idle_cycle(now_ms, t0)
    account_mod.adopt_legacy_db(our_address)

    with EngineState(account_mod.db_path(our_address)) as state:
        settings, settings_error = settings_io.load_settings(_settings_path(), state)

        if settings_error:
            log_event(EngineEvent(ts_ms=now_ms, action="error", reason=settings_error))

        close_all_summary = None
        if _close_all_path().exists():
            # Emergency close-all: flatten every copy first, then run the
            # normal cycle with entries forced off so exits keep mirroring
            # and nothing new opens while the flag stands. The api already
            # flipped `enabled` false in settings.json (it is the only writer).
            close_all_summary = core.close_all(venue, state, our_address, now_ms, log_event)
            settings = settings.model_copy(update={"enabled": False})
            if close_all_summary["remaining"] == 0:
                try:
                    _close_all_path().unlink()
                except FileNotFoundError:
                    pass
                log_event(EngineEvent(
                    ts_ms=now_ms, action="halt",
                    reason=f"close-all complete: closed {len(close_all_summary['closed'])} "
                           f"copies, entries disabled"))

        summary = core.run_cycle(settings, venue, state, our_address, now_ms, log_event,
                                 stops=read_stops())
        for addr in summary.get("stops_done") or []:
            _clear_stop(addr)
        summary["close_all"] = close_all_summary
        duration_ms = int((time.monotonic() - t0) * 1000)
        summary["ts_ms"] = now_ms
        summary["duration_ms"] = duration_ms
        # The loop sleeps the read-budget-stretched interval (engine.pacing).
        summary["poll_interval_s"] = summary.get("effective_poll_s") or settings.poll_interval_s

        status = EngineStatus(
            running=True,
            enabled=settings.enabled,
            dry_run=settings.dry_run,
            last_cycle_ms=now_ms,
            cycle_ms=duration_ms,
            our_address=our_address or None,
            equity_usd=summary["equity_usd"],
            available_margin_usd=summary["available_margin_usd"],
            day_pnl_usd=summary["day_pnl_usd"],
            halted_reason=summary["halted_reason"],
            positions=summary["positions"],
            leaders=summary["leaders"],
            effective_poll_s=summary.get("effective_poll_s"),
        )
        state.set_kv(_STATUS_KV_KEY, {
            "status": status.model_dump(mode="json"),
            "poll_interval_s": summary["poll_interval_s"],
        })
        switch.write_status(data_dir, status.model_dump(mode="json"), summary["poll_interval_s"])

        logger.info(
            "cycle ts=%d duration_ms=%d leaders=%d/%d opened=%d added=%d reduced=%d closed=%d "
            "skipped=%d enabled=%s dry_run=%s halted=%s poll_s=%s read_weight=%s",
            now_ms, duration_ms, summary["leaders_ok"], summary["leaders_total"],
            len(summary["opened"]), len(summary["added"]), len(summary["reduced"]),
            len(summary["closed"]), len(summary["skipped"]), settings.enabled, settings.dry_run,
            bool(summary["halted_reason"]), summary["poll_interval_s"], summary.get("read_weight"),
        )
        return summary


def _read_settings_lenient() -> Settings:
    try:
        return Settings.model_validate_json(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return Settings()


def _idle_cycle(now_ms: int, t0: float) -> dict:
    """No active trading account: no reads, no orders. Still writes a status
    snapshot so the UI shows the engine alive with `our_address` null."""
    settings = _read_settings_lenient()
    duration_ms = int((time.monotonic() - t0) * 1000)
    status = EngineStatus(running=True, enabled=settings.enabled, dry_run=settings.dry_run,
                          last_cycle_ms=now_ms, cycle_ms=duration_ms, our_address=None,
                          halted_reason="no active trading account")
    switch.write_status(_data_dir(), status.model_dump(mode="json"), settings.poll_interval_s)
    logger.info("cycle ts=%d idle: no active trading account", now_ms)
    return {"opened": [], "added": [], "reduced": [], "closed": [], "skipped": {"all": "no active trading account"},
            "vanished": [], "split": [], "leaders_ok": 0, "leaders_total": 0, "equity_usd": None,
            "available_margin_usd": None, "day_pnl_usd": None, "halted_reason": "no active trading account",
            "enabled": settings.enabled, "dry_run": settings.dry_run, "positions": [], "leaders": [],
            "stops_done": [], "effective_poll_s": None, "close_all": None, "ts_ms": now_ms,
            "duration_ms": duration_ms, "poll_interval_s": settings.poll_interval_s}


def run_forever(venue: Venue, max_cycles: Optional[int] = None) -> None:
    """The worker loop: calls `run_cycle` every `poll_interval_s` (read
    fresh from settings after each cycle, so a change takes effect on the
    NEXT cycle without a restart), survives any exception raised during a
    cycle (logs it, emits an `error` event, backs off exponentially up to
    60s, then tries again), and stops cleanly on SIGTERM.

    `max_cycles`: stop after this many cycles instead of running forever.
    Production callers (`python -m engine`) never pass this; it exists so
    tests can bound the loop deterministically instead of relying on
    signal timing.

    No overlap, by construction: one thread runs cycles back to back, and
    the next one starts only after the previous returned. A slow cycle
    (the ~20s first full dex scan) makes the following sleep
    `max(0, poll_interval_s - elapsed)` = 0, so cycles never stack or
    queue up; they run late, never twice. Across processes, an exclusive
    non-blocking flock on `data/engine.lock` makes a second worker on the
    same data dir raise `EngineAlreadyRunning` instead of double-trading.
    """
    lock_fh = _acquire_worker_lock()
    try:
        _run_loop(venue, max_cycles)
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fh.close()


def _acquire_worker_lock():
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    fh = open(data_dir / LOCK_FILE, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            raise EngineAlreadyRunning(
                f"another engine worker holds {data_dir / LOCK_FILE}; refusing to start a second "
                f"one on the same data dir") from exc
        raise
    return fh


def _run_loop(venue: Venue, max_cycles: Optional[int]) -> None:
    stop = {"flag": False}

    def _handle_sigterm(signum: int, frame: object) -> None:
        stop["flag"] = True

    previous_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        backoff_s = 1.0
        cycles = 0
        poll_interval_s = 5.0
        while not stop["flag"]:
            cycle_start = time.monotonic()
            try:
                summary = run_cycle(venue)
                poll_interval_s = summary.get("poll_interval_s", poll_interval_s)
                backoff_s = 1.0
            except Exception:
                logger.exception("cycle raised an exception, backing off %.1fs", backoff_s)
                try:
                    data_dir = _data_dir()
                    data_dir.mkdir(parents=True, exist_ok=True)
                    events_mod.append_event(_events_path(), EngineEvent(
                        ts_ms=int(time.time() * 1000), action="error",
                        reason="cycle raised an exception, see logs"))
                except Exception:
                    logger.exception("failed to log the cycle-exception error event")
                _sleep_interruptibly(backoff_s, stop)
                backoff_s = min(backoff_s * 2, 60.0)
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    break
                continue

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            elapsed = time.monotonic() - cycle_start
            _sleep_interruptibly(max(0.0, poll_interval_s - elapsed), stop)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _sleep_interruptibly(seconds: float, stop: dict) -> None:
    """Sleep in small slices so a SIGTERM during the sleep is noticed
    promptly instead of after the full interval."""
    end = time.monotonic() + seconds
    while not stop["flag"] and time.monotonic() < end:
        time.sleep(min(0.5, max(0.0, end - time.monotonic())))


def status(address: Optional[str] = None) -> EngineStatus:
    """The last cycle's snapshot. No venue call, no network -- safe to call from
    the api process. Default: `engine_status.json`, the cycle the engine last ran
    (whatever account was active then; `our_address` names it, null = none).
    `address`: that account's own last snapshot from its engine-<address>.db
    (e.g. copies still held by an account that is no longer active).
    `running` is a staleness heuristic (last cycle within max(30s, 3x its own
    poll_interval_s)), not a real process check.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    raw: Optional[Dict[str, Any]] = None
    if address is None:
        raw = switch.read_status(data_dir)
        legacy = data_dir / account_mod.LEGACY_DB
        if raw is None and legacy.exists():
            with EngineState(legacy) as state:
                raw = state.get_kv(_STATUS_KV_KEY)
    else:
        path = account_mod.db_path(norm_addr(address))
        if path.exists():
            with EngineState(path) as state:
                raw = state.get_kv(_STATUS_KV_KEY)
    if raw is None:
        return EngineStatus(running=False, enabled=False, dry_run=True)
    st = EngineStatus.model_validate(raw["status"])
    st.running = address is None and _is_running(st.last_cycle_ms, float(raw.get("poll_interval_s", 5.0)))
    return st


def _is_running(last_cycle_ms: Optional[int], poll_interval_s: float) -> bool:
    if last_cycle_ms is None:
        return False
    staleness_ms = max(_MIN_RUNNING_STALENESS_MS, int(poll_interval_s * 1000 * 3))
    return (int(time.time() * 1000) - last_cycle_ms) < staleness_ms


def events(limit: int = 100, since_ms: Optional[int] = None) -> List[EngineEvent]:
    """Newest first, at most `limit`, optionally only events with
    `ts_ms > since_ms`. See `engine.events.read_events`."""
    return events_mod.read_events(_events_path(), limit=limit, since_ms=since_ms)


# ── Trade ticket preview ────────────────────────────────────────────────────

class PreviewUnavailable(RuntimeError):
    """The leader's account read failed; the api maps this to 502."""


def wallet_settings(settings: Settings, address: str, req: WalletCopyRequest) -> Settings:
    """The effective settings a wallet would run with after
    POST /api/wallets/{address}/copy with `req`.
    global: the book-wide settings as they are (no override at all).
    custom: book-wide merged with its current override, then the ticket's
    fields (allocation sizing plus any per-wallet leverage and
    only_new_positions)."""
    if req.settings_source == "global":
        return settings.model_copy(update={"leader_overrides": {}})
    es = settings.for_leader(address)
    patch: Dict[str, Any] = {
        "sizing_mode": SizingMode.allocation, "allocation_usd": req.allocation_usd,
        "exposure_mode": req.exposure_mode,
    }
    for k in ("target_leverage", "margin_mode", "max_worse_entry_pct", "small_account_mode",
              "leverage_mode", "leverage", "only_new_positions"):
        v = getattr(req, k)
        if v is not None:
            patch[k] = v
    return Settings.model_validate({**es.model_dump(), **patch})


def _default_venue() -> Any:
    from hl import HlVenue  # lazy: the api imports engine.public without services/hl loaded
    return HlVenue()


def preview_wallet(address: str, req: WalletCopyRequest, settings: Settings,
                   venue: Optional[Any] = None, now_ms: Optional[int] = None) -> WalletPreview:
    """What investing `req` in `address` would copy of his book now. Read
    only: his account, each coin's max leverage, 24h volume and book depth.
    Sized by `sizing.plan_allocation` with the exact exchange leverage the
    engine would request per coin, his equity computed as the engine does
    (extras included when include_spot_staked), our existing copies of him
    held (concentrate never drops them) and their margin counted against
    the allocation cap, so re-posting a bigger amount previews the adjust."""
    venue = venue or _default_venue()
    address = norm_addr(address)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    es = wallet_settings(settings, address, req)
    acct = venue.account_state(address)
    if acct is None:
        raise PreviewUnavailable(f"account read failed for {address}")
    his_equity = sizing.account_equity(acct)
    if es.include_spot_staked:
        extras = venue.extras(address)
        if extras is None:
            raise PreviewUnavailable(f"extras read failed for {address}")
        his_equity += float(extras["spot_other_usd"]) + float(extras["staked_hype_usd"])
    positions = dict(acct.get("positions") or {})
    notes: List[str] = []
    levs: Dict[str, int] = {}
    coin_max: Dict[str, int] = {}
    for c, p in sorted(positions.items()):
        m = int(venue.max_leverage(c) or 0)
        if m <= 0:
            notes.append(f"{c}: max leverage unknown, the engine would wait")
            positions.pop(c)
            continue
        coin_max[c] = m
        levs[c] = sizing.exchange_leverage(es, float(p.get("lev") or 1.0), m)
    liq: Dict[str, Optional[float]] = {}
    for c, p in positions.items():
        try:
            stats = venue.market_stats(c)
            depth = venue.depth_usd(c, float(p.get("szi") or 0.0) > 0, es.max_slippage_pct)
        except Exception:
            stats, depth = None, None
        vol = (stats or {}).get("day_volume_usd") if stats else None
        liq[c] = sizing.liquidity_cap(vol, depth, es.max_order_volume_pct)

    held: List[str] = []
    margin_used = 0.0
    available: Optional[float] = None
    our_equity: Optional[float] = None
    known = address in settings.leaders      # the engine has (or will have) a baseline already
    open_copies = 0
    taken: Dict[str, str] = {}
    try:
        st = status()
        available = st.available_margin_usd
        our_equity = st.equity_usd
        open_copies = len(st.positions)
        taken = {p.coin: p.leader for p in st.positions if p.leader != address}
        for row in st.leaders:
            if row.address == address:
                known = True
                held = list(row.owned_coins)
                margin_used = float(row.margin_used_usd or 0.0)
    except Exception:
        logger.warning("preview: engine status unreadable, previewing as a fresh wallet",
                       exc_info=True)

    if es.sizing_mode == SizingMode.allocation:
        plan = sizing.plan_allocation(
            positions, his_equity, es.allocation_usd, es.exposure_mode, es.target_leverage,
            es.small_account_mode, coin_max, lev_by_coin=levs, held=held, liq_cap=liq,
            margin_used_usd=margin_used, max_position_leverage=es.max_position_leverage)
    else:
        n_leaders = len(settings.leaders) + (0 if address in settings.leaders else 1)
        plan = sizing.plan_copy(
            es, {c: p for c, p in positions.items() if c not in held}, his_equity, coin_max,
            our_equity=our_equity, n_leaders=n_leaders, lev_by_coin=levs, liq_cap=liq,
            open_copies=open_copies, taken=taken)
        notes.append(f"Settings tab sizing: {es.sizing_mode.value}, leverage {es.leverage_mode.value}")
    if es.only_new_positions and not known and positions:
        # first sight is a baseline: what he holds now is never copied
        for r in plan["slices"]:
            if r["status"] != "skip":
                r.update(status="skip", notional_usd=0.0, margin_usd=0.0, fill_cycles=1,
                         reason="only_new_positions: his current positions are not copied")
        plan.update(planned_notional_usd=0.0, planned_margin_usd=0.0, copied=[],
                    skipped=[r["coin"] for r in plan["slices"]], multi_cycle=False)
        notes.append("only_new_positions: only positions he opens from now on are copied")
    if not positions:
        notes.append("he holds no positions now: nothing opens until he does")
    if plan["multi_cycle"]:
        notes.append("some slices exceed the liquidity cap and fill over several cycles")
    if available is not None and plan["planned_margin_usd"] > available:
        notes.append(f"needs ${plan['planned_margin_usd']:,.2f} margin, "
                     f"${available:,.2f} is available: orders would be trimmed")
    return WalletPreview(
        address=address, as_of_ms=now_ms, allocation_usd=es.allocation_usd,
        exposure_mode=es.exposure_mode,
        target_leverage=es.target_leverage if es.exposure_mode.value == "target" else None,
        small_account_mode=es.small_account_mode, his_equity_usd=his_equity,
        his_gross_notional_usd=sizing.gross_notional(positions),
        slices=[WalletPreviewSlice(**r) for r in plan["slices"]],
        planned_notional_usd=plan["planned_notional_usd"],
        planned_margin_usd=plan["planned_margin_usd"], copied=len(plan["copied"]),
        skipped=len(plan["skipped"]),
        min_allocation_for_full_book=plan["min_allocation_for_full_book"],
        multi_cycle=plan["multi_cycle"], margin_already_used_usd=margin_used, notes=notes)
