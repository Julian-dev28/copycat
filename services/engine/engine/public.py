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
    SizingMode,
    WalletCopyRequest,
    WalletPreview,
    WalletPreviewSlice,
    Settings,
    norm_addr,
)
from contracts.venue import Venue

from . import core, events as events_mod, settings_io, sizing
from .state import EngineState

logger = logging.getLogger(__name__)

_STATUS_KV_KEY = "last_status"
_MIN_RUNNING_STALENESS_MS = 30_000


def _data_dir() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data"))


def _db_path() -> Path:
    return _data_dir() / "engine.db"


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

    with EngineState(_db_path()) as state:
        our_address = os.environ.get("COPYCAT_ACCOUNT_ADDRESS", "")
        settings, settings_error = settings_io.load_settings(_settings_path(), state)

        # Written as they happen, not batched at the end: if the cycle raises
        # after an order went through, the open/close event must still be in
        # the log, or the feed would disagree with the exchange.
        def log_event(e: EngineEvent) -> None:
            events_mod.append_event(_events_path(), e)

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

        logger.info(
            "cycle ts=%d duration_ms=%d leaders=%d/%d opened=%d added=%d reduced=%d closed=%d "
            "skipped=%d enabled=%s dry_run=%s halted=%s poll_s=%s read_weight=%s",
            now_ms, duration_ms, summary["leaders_ok"], summary["leaders_total"],
            len(summary["opened"]), len(summary["added"]), len(summary["reduced"]),
            len(summary["closed"]), len(summary["skipped"]), settings.enabled, settings.dry_run,
            bool(summary["halted_reason"]), summary["poll_interval_s"], summary.get("read_weight"),
        )
        return summary


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


def status() -> EngineStatus:
    """Read the last cycle's snapshot from SQLite. No venue call, no
    network -- safe to call from the api process, which never has a venue
    of its own. `running` is a staleness heuristic (last cycle within
    max(30s, 3x its own poll_interval_s)), not a real process check: this
    function has no way to know if the engine worker process is alive
    beyond "did it write a snapshot recently."
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    with EngineState(_db_path()) as state:
        raw = state.get_kv(_STATUS_KV_KEY)
        if raw is None:
            return EngineStatus(running=False, enabled=False, dry_run=True)
        st = EngineStatus.model_validate(raw["status"])
        poll_interval_s = float(raw.get("poll_interval_s", 5.0))
        st.running = _is_running(st.last_cycle_ms, poll_interval_s)
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
