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
"""
from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from typing import List, Optional

from contracts.models import EngineEvent, EngineStatus
from contracts.venue import Venue

from . import core, events as events_mod, settings_io
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

        pending_events: List[EngineEvent] = []

        def log_event(e: EngineEvent) -> None:
            pending_events.append(e)

        if settings_error:
            log_event(EngineEvent(ts_ms=now_ms, action="error", reason=settings_error))

        summary = core.run_cycle(settings, venue, state, our_address, now_ms, log_event)
        duration_ms = int((time.monotonic() - t0) * 1000)
        summary["ts_ms"] = now_ms
        summary["duration_ms"] = duration_ms
        summary["poll_interval_s"] = settings.poll_interval_s

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
        )
        state.set_kv(_STATUS_KV_KEY, {
            "status": status.model_dump(mode="json"),
            "poll_interval_s": settings.poll_interval_s,
        })

        for e in pending_events:
            events_mod.append_event(_events_path(), e)

        logger.info(
            "cycle ts=%d duration_ms=%d leaders=%d/%d opened=%d added=%d reduced=%d closed=%d "
            "skipped=%d enabled=%s dry_run=%s halted=%s",
            now_ms, duration_ms, summary["leaders_ok"], summary["leaders_total"],
            len(summary["opened"]), len(summary["added"]), len(summary["reduced"]),
            len(summary["closed"]), len(summary["skipped"]), settings.enabled, settings.dry_run,
            bool(summary["halted_reason"]),
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
    """
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
