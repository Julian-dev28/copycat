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
Contract v8: `leader_events(address, limit, before_ms)` (one wallet's history),
`wallet_ledgers()` and `archive_wallet(address)` (the per-wallet ledger).
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
from typing import Any, Dict, List, Optional, Tuple

from contracts import build as build_mod
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
    return {a: close for a, (close, _raw) in read_stop_flags().items()}


def read_stop_flags() -> Dict[str, Tuple[bool, str]]:
    """Like read_stops, plus each flag's raw text, so the flag can be cleared
    only if it is still the one this cycle acted on (audit M4)."""
    out: Dict[str, Tuple[bool, str]] = {}
    d = _stop_dir()
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.flag")):
        addr = norm_addr(f.stem)
        if not _ADDR_RE.match(addr):
            continue
        try:
            text = f.read_text()
        except OSError:
            out[addr] = (True, "")
            continue
        try:
            raw = json.loads(text or "{}")
            out[addr] = (bool(raw.get("close_positions", True)) if isinstance(raw, dict) else True, text)
        except ValueError:
            out[addr] = (True, text)
    return out


def _clear_stop(addr: str, seen: Optional[str] = None) -> bool:
    """Delete the stop flag. With `seen` (the text read at cycle start), only
    when the file still holds that text: a stop re-posted mid-cycle (say
    close_positions false -> true) is a NEW request and stays for the next
    cycle (audit M4). Returns True when the flag was removed."""
    path = _stop_dir() / f"{addr}.flag"
    try:
        if seen is not None and path.read_text() != seen:
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return False


class EngineAlreadyRunning(RuntimeError):
    """Another worker holds `data/engine.lock`. Two workers on one data dir
    would each diff the same leaders and both place the same orders."""


def _pin_credentials() -> Any:
    """hl.env.pin_credentials(), or None when hl is not importable (tests that
    run the engine with a fake venue and no hl package on the path)."""
    try:
        from hl import env as hl_env
    except Exception:
        return None
    try:
        return hl_env.pin_credentials()
    except Exception:
        return None


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
    # Re-resolved every cycle: activating another account in the vault switches
    # the engine at the next cycle, onto that account's own state db.
    our_address = account_mod.resolve_our_address()

    def log_event(e: EngineEvent) -> None:
        if e.account is None and our_address:
            e = e.model_copy(update={"account": norm_addr(our_address)})   # audit M10
        events_mod.append_event(_events_path(), e)

    switched_from = switch.note_account(data_dir, our_address, now_ms, log_event)
    if not our_address:
        return _idle_cycle(now_ms, t0)
    # Audit B2: pin (account, agent key) once for the whole cycle. Every write
    # signs with these; the venue refuses a write if the active account changes
    # mid-cycle. A pin for a different account than the one we read means a
    # switch landed between the two reads: skip this cycle, the next one is clean.
    creds = _pin_credentials()
    if creds is not None and creds.account != our_address.lower():
        log_event(EngineEvent(ts_ms=now_ms, action="error",
                              reason="active account changed while the cycle started; skipped"))
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
            close_all_summary = core.close_all(venue, state, our_address, now_ms, log_event,
                                               creds=creds)
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

        stop_flags = read_stop_flags()
        summary = core.run_cycle(settings, venue, state, our_address, now_ms, log_event,
                                 stops={a: c for a, (c, _t) in stop_flags.items()}, creds=creds,
                                 switched_in=switched_from is not None)
        for addr in summary.get("stops_done") or []:
            _clear_stop(addr, stop_flags.get(addr, (True, None))[1])
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
            day_pnl_reliable=summary.get("day_pnl_reliable", True),
            day_pnl_unreliable_since_ms=summary.get("day_pnl_unreliable_since_ms"),
            halted_reason=summary["halted_reason"],
            positions=summary["positions"],
            leaders=summary["leaders"],
            effective_poll_s=summary.get("effective_poll_s"),
        )
        state.set_kv(_STATUS_KV_KEY, {
            "status": status.model_dump(mode="json"),
            "poll_interval_s": summary["poll_interval_s"],
        })
        switch.write_status(data_dir, status.model_dump(mode="json"), summary["poll_interval_s"],
                            build=build_mod.record("engine"))

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
    switch.write_status(_data_dir(), status.model_dump(mode="json"), settings.poll_interval_s,
                        build=build_mod.record("engine"))
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


def process_build() -> Optional[Dict[str, Any]]:
    """The running engine's build info (contracts.build) from its status
    file, plus `alive` (last cycle recent, as `status().running`). None when
    the engine never wrote one (not started, or started on code older than
    the version-skew guard: treat as unknown/old)."""
    raw = switch.read_status(_data_dir())
    if not raw or not isinstance(raw.get("build"), dict):
        return None
    st = EngineStatus.model_validate(raw["status"])
    return {**raw["build"], "alive": _is_running(st.last_cycle_ms, float(raw.get("poll_interval_s", 5.0)))}


def _is_running(last_cycle_ms: Optional[int], poll_interval_s: float) -> bool:
    if last_cycle_ms is None:
        return False
    staleness_ms = max(_MIN_RUNNING_STALENESS_MS, int(poll_interval_s * 1000 * 3))
    return (int(time.time() * 1000) - last_cycle_ms) < staleness_ms


def active_account() -> Optional[str]:
    """The trading account the engine runs for now (lowercase), or None."""
    try:
        a = account_mod.resolve_our_address()
    except Exception:
        return None
    return norm_addr(a) if a else None


def events(limit: int = 100, since_ms: Optional[int] = None) -> List[EngineEvent]:
    """Newest first, at most `limit`, optionally only events with
    `ts_ms > since_ms`, for the ACTIVE account only (audit M10). See
    `engine.events.read_events`."""
    return events_mod.read_events(_events_path(), limit=limit, since_ms=since_ms,
                                  account=active_account())


def leader_events(address: str, limit: int = 50,
                  before_ms: Optional[int] = None) -> List[EngineEvent]:
    """One wallet's events (actions + skips with reasons) on the ACTIVE
    account (audit M10), newest first, `ts_ms < before_ms` when given. Reads
    events.jsonl from the tail with a capped scan (`engine.events.read_leader_events`)."""
    return events_mod.read_leader_events(_events_path(), norm_addr(address), limit=limit,
                                         before_ms=before_ms, account=active_account())


# ── wallet ledger: archive (contract v8) ────────────────────────────────────

class ArchiveRefused(ValueError):
    """The wallet still has copies on the active account; the api maps it to 409."""


def wallet_ledgers(address: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Every per-wallet ledger row of an account's db (default: the active
    account): leader -> {invested_ms, realized_pnl_usd, fees_usd, terms,
    updated_ms, archived_ms}. No venue, no network. {} when there is no
    account or no db yet."""
    try:
        path = _db_path(norm_addr(address) if address else None)
    except Exception:
        return {}
    if not path.exists():
        return {}
    with EngineState(path) as state:
        return state.all_ledgers()


def archive_wallet(address: str, now_ms: Optional[int] = None) -> Dict[str, Any]:
    """Mark a stopped wallet archived in the active account's ledger. Refuses
    (ArchiveRefused) while any copy row of it, real or dry-run shadow, still
    exists: the engine keeps reading an archived wallet only while it holds
    copies, so archiving one would never stop its exits, but the rule keeps
    "archived" meaning "nothing left". The api checks the book and stop
    flags. Returns the ledger row."""
    addr = norm_addr(address)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    our = account_mod.resolve_our_address()
    if not our:
        raise ArchiveRefused("no active account")
    with EngineState(account_mod.db_path(our)) as state:
        held = sorted({c.coin for c in state.all_copies() if c.leader == addr}
                      | {c.coin for c in state.all_dry_copies() if c.leader == addr})
        if held:
            raise ArchiveRefused(f"{addr} still has copies: {', '.join(held)}")
        state.archive_ledger(addr, now_ms)
        return state.get_ledger(addr) or {}


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
              "leverage_mode", "leverage", "only_new_positions", "trade_direction",
              "coin_allowlist", "coin_blocklist"):
        v = getattr(req, k)
        if v is not None:
            patch[k] = v
    return Settings.model_validate({**es.model_dump(), **patch})


def _apply_v8_to_plan(plan: Dict[str, Any], es: Settings, notes: List[str]) -> None:
    """Contract v8 on a preview plan, the way the engine applies it: sized on
    their whole book first (a filtered coin's slice is left unspent, never
    handed to the other coins), then a coin outside the allow/block lists is
    skipped "filtered: <coin>", every side flips for counter, and a paused
    wallet copies nothing until resumed."""
    counter = es.trade_direction.value == "counter"
    changed = False
    for r in plan["slices"]:
        if counter:
            r["side"] = "short" if r["side"] == "long" else "long"
        if r["status"] not in sizing.NOT_COPIED and not sizing.coin_allowed(es, r["coin"]):
            r.update(status="skip", notional_usd=0.0, margin_usd=0.0, fill_cycles=1,
                     reason=f"filtered: {r['coin']}")
            changed = True
    if counter:
        notes.append("counter: every copy takes the opposite side of their position")
    if es.paused:
        notes.append("paused: nothing opens until the wallet is resumed")
    if changed:
        live = [r for r in plan["slices"] if r["status"] not in sizing.NOT_COPIED]
        plan.update(planned_notional_usd=round(sum(r["notional_usd"] for r in live), 6),
                    planned_margin_usd=round(sum(r["margin_usd"] for r in live), 6),
                    copied=[r["coin"] for r in live],
                    skipped=[r["coin"] for r in plan["slices"] if r["status"] == "skip"],
                    multi_cycle=any(int(r.get("fill_cycles") or 1) > 1 for r in live))


def _default_venue() -> Any:
    from hl import HlVenue  # lazy: the api imports engine.public without services/hl loaded
    return HlVenue()


def leader_book(address: str, venue: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Their open perp positions from ONE account read (no per-coin reads), as
    [{coin, side, notional_usd}] with notional = |size| x their entry (what the
    engine sizes from). The api's MCP copy plan hashes this to detect that their
    book changed between a plan and its execute. PreviewUnavailable if the
    read fails."""
    venue = venue or _default_venue()
    acct = venue.account_state(norm_addr(address))
    if acct is None:
        raise PreviewUnavailable(f"account read failed for {address}")
    out: List[Dict[str, Any]] = []
    for c, p in sorted((acct.get("positions") or {}).items()):
        szi = float(p.get("szi") or 0.0)
        if szi:
            out.append({"coin": c, "side": "long" if szi > 0 else "short",
                        "notional_usd": sizing.his_notional(p)})
    return out


def preview_wallet(address: str, req: WalletCopyRequest, settings: Settings,
                   venue: Optional[Any] = None, now_ms: Optional[int] = None) -> WalletPreview:
    """What investing `req` in `address` would copy of their book now. Read
    only: their account, each coin's max leverage, 24h volume and book depth.
    Sized by `sizing.plan_allocation` with the exact exchange leverage the
    engine would request per coin, their equity computed as the engine does
    (extras included when include_spot_staked), our existing copies of them
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
    unknown_max: Dict[str, str] = {}
    for c, p in sorted(positions.items()):
        m = int(venue.max_leverage(c) or 0)
        if m <= 0:
            # Audit S6: keep it in his book (the engine's lead_gross is his whole
            # book, so every target slice is n/gross of ALL of it); it waits.
            unknown_max[c] = "max leverage unknown: the engine waits and re-checks every cycle"
            continue
        coin_max[c] = m
        levs[c] = sizing.exchange_leverage(es, float(p.get("lev") or 1.0), m)
    liq: Dict[str, Optional[float]] = {}
    mids: Dict[str, float] = {}
    for c, p in positions.items():
        try:
            stats = venue.market_stats(c)
            # our order side: his side, inverted for counter (v8)
            depth = venue.depth_usd(c, sizing.our_is_long(float(p.get("szi") or 0.0),
                                                          es.trade_direction), es.max_slippage_pct)
        except Exception:
            stats, depth = None, None
        vol = (stats or {}).get("day_volume_usd") if stats else None
        liq[c] = sizing.liquidity_cap(vol, depth, es.max_order_volume_pct)
        try:
            mids[c] = float((stats or {}).get("mid_px") or 0.0) or float(venue.mid(c) or 0.0)
        except Exception:
            mids[c] = 0.0

    # Engine gates that run before sizing (core._diff_coin), in its order:
    # coin filter, then max_worse_entry_pct against HIS entry on OUR side.
    pre_skip: Dict[str, str] = {c: f"filtered: {c}" for c in positions if not sizing.coin_allowed(es, c)}
    wait: Dict[str, str] = {}
    for c, p in positions.items():
        if c in pre_skip:
            continue
        why = sizing.entry_wait_reason(sizing.our_is_long(float(p.get("szi") or 0.0), es.trade_direction),
                                       mids.get(c, 0.0), float(p.get("entry_px") or 0.0),
                                       es.max_worse_entry_pct)
        if why:
            wait[c] = why
    for c, why in unknown_max.items():
        if c not in pre_skip:
            wait[c] = why

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
            margin_used_usd=margin_used, max_position_leverage=es.max_position_leverage,
            pre_skip={**{c: f"owned by wallet {w}" for c, w in taken.items()}, **pre_skip}, wait=wait,
            max_open_copies=es.max_open_copies, open_copies=open_copies)
    else:
        n_leaders = len(settings.leaders) + (0 if address in settings.leaders else 1)
        plan = sizing.plan_copy(
            es, {c: p for c, p in positions.items() if c not in held}, his_equity, coin_max,
            our_equity=our_equity, n_leaders=n_leaders, lev_by_coin=levs, liq_cap=liq,
            open_copies=open_copies, taken=taken, pre_skip=pre_skip, wait=wait)
        notes.append(f"Settings tab sizing: {es.sizing_mode.value}, leverage {es.leverage_mode.value}")
    if es.only_new_positions and not known and positions:
        # first sight is a baseline: what he holds now is never copied
        for r in plan["slices"]:
            if r["status"] != "skip":     # incl. "wait": his current book is never copied
                r.update(status="skip", notional_usd=0.0, margin_usd=0.0, fill_cycles=1,
                         reason="only_new_positions: their current positions are not copied")
        plan.update(planned_notional_usd=0.0, planned_margin_usd=0.0, copied=[], waiting=[],
                    skipped=[r["coin"] for r in plan["slices"]], multi_cycle=False)
        notes.append("only_new_positions: only positions they open from now on are copied")
    _apply_v8_to_plan(plan, es, notes)
    if not positions:
        notes.append("they hold no positions now: nothing opens until they do")
    if plan.get("waiting"):
        notes.append(f"waiting on price: {', '.join(plan['waiting'])} (mid is more than "
                     f"{es.max_worse_entry_pct:g}% past their entry; the engine opens it only once price "
                     f"comes back, not counted in the totals)")
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
        skipped=len(plan["skipped"]), waiting=len(plan.get("waiting") or []),
        min_allocation_for_full_book=plan["min_allocation_for_full_book"],
        multi_cycle=plan["multi_cycle"], margin_already_used_usd=margin_used, notes=notes)
