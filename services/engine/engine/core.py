"""The copy cycle: diff every leader's positions against last cycle and
mirror the changes, one net position per coin across the whole book. Ported
from pathiel's `copycat_live.maybe_run` (sibling repo, commit ab2e800) onto
`contracts.models`/`contracts.venue` and SQLite state instead of pathiel's
JSON-file state and claims registry. `services/engine/README.md` has the
plain-English rule set; every rule below is pinned by a gate test.

Kept from pathiel:
  - one leader owns a coin at a time (first to open it keeps it until OUR
    copy of it closes)
  - a leader read failure skips only that leader and never looks like him
    going flat
  - exits (reduce/close/flip) mirror regardless of `enabled`. `dry_run` is
    a different axis: it blocks ALL writes, exits included
  - a failed exit is retried every cycle until it succeeds (by freezing
    `last_positions[coin]` at the stale value so the diff keeps re-firing)
  - a flip (long<->short in one read) is a close then a fresh open
  - `max_worse_entry_pct` gates opens/adds only, and the skip is PENDING
  - `min_order_bump` only bumps an open/add that is already close to the
    floor; reduces are never bumped
  - orphan leaders keep exiting, never get new exposure
  - "our copy vanished" stops mirroring that coin until the leader is flat

Added for the standalone product:
  - "not ours": a real position in a coin with no `copies` row is never
    touched and never copied into
  - `daily_loss_limit_usd` / `max_open_copies` risk gates
  - `dry_run` with a shadow `dry_copies` table
  - the pending-row protocol for opens (row written before the order, keyed
    by a client order id) and pending reduces, so a crash or an ambiguous
    (timed out) order result can never leave an untracked real position or
    double a reduce
  - cycle-start reconciles: pending orders, vanished copies (liquidations
    the leader diff cannot see), stranded copies the leader no longer holds
  - per-leader and per-coin exception isolation: one bad leader or coin
    never stops the exits of every leader after it
  - emergency `close_all`
  - Trade page wallets (`sizing_mode` allocation): allocation sizing with
    small-account concentrate/bump/skip and a per-wallet margin cap, a
    per-leader realized-PnL ledger, and stop-one-wallet (`stops`)
  - liquidity caps: an open/add is capped at a share of the coin's 24h
    volume and the book depth within the slippage cap; the rest is carried
    as a catch-up and sent over the next cycles
  - read-budget pacing (`engine.pacing`): the effective poll interval
    stretches with the number of accounts read
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from contracts.models import (
    HL_MIN_ORDER_USD,
    CopyPosition,
    EngineEvent,
    LeaderStatus,
    MarginMode,
    Settings,
    SizingMode,
    SmallAccountMode,
)
from contracts.venue import Venue

from . import pacing, sizing
from .state import Copy, DryCopy, EngineState, LeaderState

logger = logging.getLogger(__name__)

LogEvent = Callable[[EngineEvent], None]

# A fill this close to the requested size is a full fill: HL rounds sizes to
# szDecimals, never by a relative 1e-6.
_FULL_FILL_TOL = 1e-6

_MARKS_KEY = "last_marks"                 # coin -> last seen liq/mark px of OUR copy
_VANISH_PENDING_KEY = "vanish_pending"    # coin -> ts_ms of the first read it was missing
_PENDING_REDUCES_KEY = "pending_reduces"  # coin -> ambiguous reduce awaiting resolution
_LAST_DRY_RUN_KEY = "last_dry_run"
_CATCH_UP_KEY = "catch_up"                # coin -> unfilled remainder of a liquidity-split entry
STOP_REASON = "stop wallet"
VANISHED_REASON = "our copy vanished (liquidated or closed outside copycat)"
# order_status values that mean "not settled yet, ask again next cycle"
_UNSETTLED = (None, "open")
# "unknown" right after sending can mean HL has not processed the order yet;
# only believe it once the order is this old.
_UNKNOWN_GRACE_MS = 30_000


def _settled(status: Optional[str], sent_ms: int, now_ms: int) -> bool:
    if status in _UNSETTLED:
        return False
    if status == "unknown" and now_ms - sent_ms < _UNKNOWN_GRACE_MS:
        return False
    return True


def new_cloid() -> str:
    """HL client order id: 0x + 32 hex chars (16 random bytes)."""
    return "0x" + secrets.token_hex(16)


def _filled(res: Dict[str, Any]) -> float:
    try:
        return float(res.get("filled_sz") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _partial(res: Dict[str, Any], wanted: float) -> bool:
    """True when an order filled SOME but measurably less than `wanted`.
    Contract v2 reports a partial as `ok False` + `filled_sz > 0`; an `ok
    True` with a short `filled_sz` is treated the same, defensively. No
    `filled_sz` at all is not partial: there is nothing to compare."""
    f = _filled(res)
    if f <= 0 or wanted <= 0:
        return False
    return f < wanted * (1 - _FULL_FILL_TOL)


def _full(res: Dict[str, Any], wanted: float) -> bool:
    return bool(res.get("ok")) and not _partial(res, wanted)


def _szi(positions: Dict[str, Any], coin: str) -> float:
    return float((positions.get(coin) or {}).get("szi") or 0.0)


class _Cycle:
    """Everything one cycle shares. Not persisted; rebuilt every cycle."""

    def __init__(self, settings: Settings, venue: Venue, state: EngineState, now_ms: int,
                 log_event: LogEvent, out: Dict[str, Any]):
        self.settings = settings
        self.venue = venue
        self.state = state
        self.now_ms = now_ms
        self.log_event = log_event
        self.out = out
        self.dry = settings.dry_run
        self.our_positions: Dict[str, Any] = {}
        self.available: Dict[str, float] = {}
        self.shared_margin = False   # unified/portfolio margin: one pool repeated under every dex key
        self.equity_usd = 0.0
        self.n_leaders = 1
        self.entries_ok = False
        # the leader being diffed right now: his whole book, for allocation sizing
        self.lead_pos: Dict[str, Any] = {}
        self.lead_gross = 0.0
        # margin sent this cycle per leader (the account read predates it)
        self.alloc_spent: Dict[str, float] = {}
        self.leader_coins: Dict[str, List[str]] = {}   # for read-budget pacing
        self.raw_positions: Dict[str, Any] = {}
        self.entry_coins: Set[str] = set()     # coins with an entry this cycle (no catch-up on top)
        self.cur_leader: Optional[str] = None  # the leader being diffed (tags his skip events)

    def event(self, action: str, **kw: Any) -> None:
        self.log_event(EngineEvent(ts_ms=self.now_ms, action=action, **kw))

    def skip(self, coin: str, reason: str, leader: Optional[str] = None) -> None:
        """A coin's skip reason this cycle. The leader it belongs to (given, or
        the one being diffed) rides along so the `skip` event carries it and
        GET /api/wallets/{a}/events can show a wallet its own skips."""
        self.out["skipped"][coin] = reason
        who = leader or self.cur_leader
        if who:
            self.out.setdefault("skip_leaders", {})[coin] = who


def run_cycle(settings: Settings, venue: Venue, state: EngineState, our_address: str,
              now_ms: int, log_event: LogEvent,
              stops: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """One full cycle. Everything it does goes through `venue` and `state`.
    Returns a plain summary dict; `engine.public.run_cycle` wraps this with
    settings reload, the SQLite `EngineStatus` snapshot and the one-line log.

    `stops`: address -> close_positions, from `data/stop/<address>.flag`
    (POST /api/wallets/{address}/stop). A stopped wallet is an orphan this
    cycle even if settings still list it. `out["stops_done"]` lists the
    addresses whose flag may be deleted now.
    """
    out: Dict[str, Any] = {
        "opened": [], "added": [], "reduced": [], "closed": [], "skipped": {}, "vanished": [],
        "split": [], "leaders_ok": 0, "leaders_total": 0,
        "equity_usd": None, "available_margin_usd": None, "day_pnl_usd": None,
        "halted_reason": None, "enabled": settings.enabled, "dry_run": settings.dry_run,
        "positions": [], "leaders": [], "stops_done": [], "effective_poll_s": None,
    }
    stops = {a.lower(): bool(c) for a, c in (stops or {}).items()}
    cy = _Cycle(settings, venue, state, now_ms, log_event, out)

    last_dry = state.get_kv(_LAST_DRY_RUN_KEY)
    if last_dry is not None and bool(last_dry) != settings.dry_run:
        # The shadow book only means something within one dry-run stretch.
        state.clear_dry_copies()
        state.set_kv(_CATCH_UP_KEY, {})
    state.set_kv(_LAST_DRY_RUN_KEY, settings.dry_run)

    our_account = venue.account_state(our_address) if our_address else None
    if our_account is None:
        out["skipped"]["all"] = "our account read failed"
        cy.event("error", reason="our account read failed")
        return out

    equity_usd = sizing.account_equity(our_account)
    out["equity_usd"] = equity_usd
    shared_margin = our_account.get("abstraction") in sizing.UNIFIED_ABSTRACTIONS
    avail_vals = [float(v) for v in our_account["available"].values()]
    # Unified/portfolio margin: hl repeats ONE spot pool under every dex key, so
    # summing would count it once per dex read.
    out["available_margin_usd"] = (max(avail_vals, default=0.0) if shared_margin
                                   else sum(avail_vals))
    if equity_usd <= 0:
        out["skipped"]["all"] = "degraded account read (equity <= 0)"
        cy.event("error", reason="degraded account read (equity <= 0)")
        return out

    day_pnl_usd = _update_day_pnl(state, now_ms, equity_usd)
    out["day_pnl_usd"] = day_pnl_usd
    halted_reason = _halt_check(state, settings, day_pnl_usd, log_event, now_ms)
    out["halted_reason"] = halted_reason

    cy.equity_usd = equity_usd
    cy.entries_ok = settings.enabled and halted_reason is None
    cy.available = dict(our_account["available"])
    cy.shared_margin = shared_margin
    # Local copy: a coin we close this cycle is flat for the rest of it.
    cy.our_positions = dict(our_account["positions"])
    cy.raw_positions = dict(our_account.get("raw_positions") or {})

    configured = [a for a in settings.leaders if a not in stops]
    configured_set = set(configured)
    for leader in configured:
        es = settings.for_leader(leader)
        # any wallet with invested_ms (custom allocation, or a global copy, whose
        # override holds only invested_ms) gets its ledger reset on a re-invest
        if es.invested_ms is not None:
            state.sync_ledger(leader, es.invested_ms, _terms(es), now_ms)

    if not cy.dry:
        _resolve_pending(cy)
        _reconcile_vanished(cy)

    stopping: Set[str] = set()
    for addr, close_positions in sorted(stops.items()):
        try:
            if _run_stop(cy, addr, close_positions):
                out["stops_done"].append(addr)
            else:
                stopping.add(addr)
        except Exception as exc:  # a stop must never block the rest of the cycle
            logger.exception("stop for %s raised", addr)
            cy.event("error", leader=addr, reason=f"stop wallet raised {type(exc).__name__}: {exc}")
            stopping.add(addr)

    # An archived wallet (POST /api/wallets/{a}/archive: stopped, no copies) is no
    # longer read every cycle. Holding any copy (real or shadow) or a pending stop
    # keeps it an orphan regardless, so its exits always mirror.
    holders = {c.leader for c in state.all_copies()} | {c.leader for c in state.all_dry_copies()}
    archived = {a for a, led in state.all_ledgers().items() if led.get("archived_ms")}
    orphans = sorted(a for a in state.leader_addresses()
                     if a not in configured_set
                     and (a not in archived or a in holders or a in stops))
    order = configured + orphans
    out["leaders_total"] = len(order)
    cy.n_leaders = max(1, len(configured))

    leader_rows: List[Dict[str, Any]] = []
    for leader in order:
        es = settings.for_leader(leader)
        try:
            row = _run_leader(cy, leader, es, leader not in configured_set)
        except Exception as exc:  # one bad leader must never stop the others' exits
            logger.exception("leader %s raised during the cycle", leader)
            cy.event("error", leader=leader, reason=f"leader cycle raised {type(exc).__name__}: {exc}")
            out["skipped"][f"leader:{leader}"] = "leader cycle raised, see logs"
            row = _failed_leader_row(state, leader, es)
        leader_rows.append(row)

    out["positions"] = _build_positions(state, our_account, now_ms)
    _fill_wallet_fields(state, leader_rows, out["positions"], cy.raw_positions, stopping,
                        configured_set)
    out["leaders"] = [LeaderStatus(**r) for r in leader_rows]
    weight = pacing.cycle_weight(list(our_account["positions"]), cy.leader_coins,
                                 include_extras=settings.include_spot_staked)
    out["read_weight"] = weight
    out["effective_poll_s"] = round(pacing.effective_poll_s(settings.poll_interval_s, weight), 3)
    _log_skip_changes(state, out["skipped"], now_ms, log_event, settings.dry_run,
                      out.get("skip_leaders") or {})
    return out


def _terms(es: Settings) -> Dict[str, Any]:
    """The allocation terms a wallet runs with, remembered in its ledger row
    so a stopped (orphan) wallet's winding-down row can still show them."""
    return {"sizing_mode": es.sizing_mode.value, "allocation_usd": es.allocation_usd,
            "exposure_mode": es.exposure_mode.value, "target_leverage": es.target_leverage,
            "small_account_mode": es.small_account_mode.value, "invested_ms": es.invested_ms,
            "trade_direction": es.trade_direction.value,
            "coin_allowlist": list(es.coin_allowlist), "coin_blocklist": list(es.coin_blocklist)}


# ── one leader ──────────────────────────────────────────────────────────────

def _run_leader(cy: _Cycle, leader: str, es: Settings, is_orphan: bool) -> Dict[str, Any]:
    state, venue, out = cy.state, cy.venue, cy.out
    cy.cur_leader = leader
    lead_account = venue.account_state(leader)
    if lead_account is None:
        out["skipped"][f"leader:{leader}"] = "leader read failed"
        return _failed_leader_row(state, leader, es)

    if es.include_spot_staked:
        extras = venue.extras(leader)
        if extras is None:
            out["skipped"][f"leader:{leader}"] = "extras read failed"
            return _failed_leader_row(state, leader, es)
        his_equity = (sizing.account_equity(lead_account)
                      + float(extras["spot_other_usd"]) + float(extras["staked_hype_usd"]))
    else:
        his_equity = sizing.account_equity(lead_account)

    now_pos = lead_account["positions"]
    cy.leader_coins[leader] = list(now_pos)
    cy.lead_pos = now_pos
    cy.lead_gross = sizing.gross_notional(now_pos)
    lstate = state.get_leader(leader)
    if lstate is None:
        if es.only_new_positions:          # per-wallet override, else the Settings tab
            state.put_leader(LeaderState(leader, {c: p["szi"] for c, p in now_pos.items()},
                                         sorted(now_pos.keys()), cy.now_ms))
            cy.event("baseline", leader=leader,
                     reason=("ignoring pre-existing: " + ",".join(sorted(now_pos.keys()))
                             if now_pos else "no pre-existing positions"))
            out["leaders_ok"] += 1
            return {"address": leader, "read_ok": True, "equity_usd": his_equity,
                    "open_positions": len(now_pos), "owned_coins": [],
                    "last_read_ms": cy.now_ms, "effective": es}
        lstate = LeaderState(leader, {}, [], cy.now_ms)

    last = dict(lstate.last_positions)
    ignored = set(lstate.ignored)
    retry: Dict[str, float] = {}

    if not cy.dry:
        # Stranded copy: we hold a confirmed copy for this leader, he is flat
        # on it now, but his last-seen size is ALSO flat, so the diff would
        # never fire a close (e.g. he exited while we were in dry_run on an
        # older build, or state was restored from a backup). Seed a nonzero
        # `prev` so the normal close path (with its retry) runs.
        for c in state.all_copies():
            if (c.leader == leader and c.pending_cloid is None and c.coin not in now_pos
                    and not float(last.get(c.coin) or 0.0) and _szi(cy.our_positions, c.coin)):
                # his last-seen sign: ours for a copy, the opposite for a counter copy
                ours_long = _szi(cy.our_positions, c.coin) > 0
                last[c.coin] = 1.0 if ours_long == (c.direction == "copy") else -1.0
                ignored.discard(c.coin)

    pending_reduces = state.get_kv(_PENDING_REDUCES_KEY) or {}

    for coin in sorted(set(last) | set(now_pos)):
        prev = float(last.get(coin) or 0.0)
        cur = float((now_pos.get(coin) or {}).get("szi") or 0.0)
        if prev == cur:
            continue
        try:
            _diff_coin(cy, leader, es, is_orphan, coin, prev, cur, now_pos, his_equity,
                       ignored, retry, pending_reduces)
        except Exception as exc:  # one bad coin must never stop the rest
            logger.exception("coin %s for leader %s raised", coin, leader)
            cy.event("error", leader=leader, coin=coin,
                     reason=f"coin step raised {type(exc).__name__}: {exc}")
            out["skipped"][coin] = "coin step raised, see logs"
            if abs(cur) < abs(prev) or (prev and cur and (prev > 0) != (cur > 0)):
                retry[coin] = prev          # exits keep retrying
            elif state.get_copy(coin) is None:
                ignored.add(coin)           # never re-fire an entry that may have gone through

    try:
        _catch_up(cy, leader, es, is_orphan, now_pos, retry)
    except Exception as exc:  # a catch-up must never cost the leader his state write
        logger.exception("catch-up for leader %s raised", leader)
        cy.event("error", leader=leader, reason=f"catch-up raised {type(exc).__name__}: {exc}")

    new_last = {c: p["szi"] for c, p in now_pos.items()}
    for coin, frozen_prev in retry.items():
        new_last[coin] = frozen_prev
    state.put_leader(LeaderState(leader, new_last, sorted(ignored), cy.now_ms))
    out["leaders_ok"] += 1
    return {
        "address": leader, "read_ok": True, "equity_usd": his_equity,
        "open_positions": len(now_pos),
        "owned_coins": _owned_coins(state, leader, cy.dry),
        "last_read_ms": cy.now_ms, "effective": es,
    }


def _diff_coin(cy: _Cycle, leader: str, es: Settings, is_orphan: bool, coin: str, prev: float,
               cur: float, now_pos: Dict[str, Any], his_equity: float, ignored: Set[str],
               retry: Dict[str, float], pending_reduces: Dict[str, Any]) -> None:
    state, venue, out = cy.state, cy.venue, cy.out
    flipped = bool(prev) and bool(cur) and (prev > 0) != (cur > 0)

    real = state.get_copy(coin)
    if cy.dry and real is not None and real.leader == leader:
        # A REAL copy opened while live. dry_run never trades it, and must not
        # let his move slip by either: freeze his last size so the diff
        # re-fires (and the real copy follows him) once live again.
        cy.skip(coin, "real copy held: dry_run defers mirroring it until live")
        retry[coin] = prev
        return

    existing = state.get_dry_copy(coin) if cy.dry else real
    if existing is not None and existing.leader != leader:
        cy.skip(coin, f"owned by leader {existing.leader}")
        return

    if not cy.dry and existing is not None and existing.pending_cloid:
        cy.skip(coin, "open order outcome unknown, resolving")
        retry[coin] = prev
        return
    if not cy.dry and coin in pending_reduces:
        cy.skip(coin, "reduce order outcome unknown, resolving")
        retry[coin] = prev
        return

    if coin in ignored:
        if cur and not flipped:
            return
        ignored.discard(coin)
        if not cur:
            return
        prev = 0.0  # a flip, or a fresh nonzero value after un-ignoring, is a fresh open

    copy = existing

    if not cy.dry and copy is not None and not cy.our_positions.get(coin):
        # Missing from this read. `_reconcile_vanished` marked it pending and
        # confirms it next cycle. Never trade on a position one read says is
        # not there; freeze `prev` so his move is re-diffed.
        cy.skip(coin, "our copy is missing from the account read, confirming next cycle")
        retry[coin] = prev
        return

    if copy is not None and (not cur or flipped):
        if not _do_close(cy, coin, leader):
            out["skipped"].setdefault(coin, "close failed, retrying next cycle")
            retry[coin] = prev
            return
        if not flipped:
            return
        copy, prev = None, 0.0

    if copy is not None and abs(cur) < abs(prev):
        ok, retry_prev = _do_reduce(cy, coin, leader, prev, cur, pending_reduces)
        if not ok:
            retry[coin] = retry_prev
        return

    if abs(cur) <= abs(prev):
        return

    lp = now_pos[coin]
    if is_orphan:
        if copy is None and cur:
            ignored.add(coin)
        cy.skip(coin, "orphan leader: no new exposure")
        return
    if not cy.entries_ok:
        if copy is None and cur:
            ignored.add(coin)
        cy.skip(coin, "entries blocked" if cy.settings.enabled else "disabled")
        return
    # v8 per-wallet entry gates. Like "disabled": a fresh open he makes while
    # gated is ignored until he goes flat (never entered midway later); an add
    # to a copy we hold is just not mirrored. Exits never reach this point.
    if es.paused:
        if copy is None and cur:
            ignored.add(coin)
        cy.skip(coin, "paused")
        return
    if not sizing.coin_allowed(es, coin):
        if copy is None and cur:
            ignored.add(coin)
        cy.skip(coin, f"filtered: {coin}")
        return
    # Our side. A copy we hold keeps the direction it was opened with; only a
    # fresh open (incl. the open half of a flip) takes the wallet's current one.
    direction = copy.direction if copy is not None else es.trade_direction.value
    is_long = sizing.our_is_long(cur, direction)
    if copy is not None and not cy.dry:
        ours = _szi(cy.our_positions, coin)
        if ours and (ours > 0) != is_long:
            # Our real position is on the other side from what this copy should
            # hold (changed outside copycat). Adding would net against it.
            cy.skip(coin, f"our {coin} position is {'long' if ours > 0 else 'short'}, this "
                          f"{direction} copy should be {'long' if is_long else 'short'}: add skipped")
            return
    mid = venue.mid(coin)
    if mid <= 0:
        cy.skip(coin, "no mid")
        retry[coin] = prev
        return
    entry_px = float(lp.get("entry_px") or 0.0)
    side = "long" if is_long else "short"          # OUR side vs HIS entry
    if not sizing.worse_entry_ok(side, mid, entry_px, es.max_worse_entry_pct):
        cy.skip(coin, f"mid {mid:.6g} worse than entry {entry_px:.6g} by more than "
                      f"{es.max_worse_entry_pct:.1f}%")
        retry[coin] = prev
        return
    if _open_or_add(cy, es, coin, leader, cur, prev, lp, his_equity, mid, ignored, copy,
                    is_long, direction) == "retry":
        retry[coin] = prev


def _log_skip_changes(state: EngineState, skipped: Dict[str, str], now_ms: int,
                      log_event: LogEvent, dry_run: bool,
                      skip_leaders: Optional[Dict[str, str]] = None) -> None:
    """Write a `skip` event when a coin's (or leader's) skip reason first
    appears or changes, not every cycle. Reasons are compared with numbers
    stripped: "mid 182.58 worse than entry 111.38" re-firing every 5s as the
    price ticks would bury everything else in the feed."""
    prev = state.get_kv("last_skips")
    prev = prev if isinstance(prev, dict) else {}
    now_sig = {k: _NUMBERS.sub("#", v) for k, v in skipped.items()}
    for key, reason in skipped.items():
        if prev.get(key) == now_sig[key]:
            continue
        leader = (key.split(":", 1)[1] if key.startswith("leader:")
                  else (skip_leaders or {}).get(key))
        coin = None if key.startswith("leader:") else key
        log_event(EngineEvent(ts_ms=now_ms, action="skip", leader=leader, coin=coin,
                              reason=reason, dry_run=dry_run))
    state.set_kv("last_skips", now_sig)


_NUMBERS = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def _failed_leader_row(state: EngineState, leader: str, es: Settings) -> Dict[str, Any]:
    existing_ls = state.get_leader(leader)
    return {
        "address": leader, "read_ok": False, "equity_usd": None, "open_positions": 0,
        "owned_coins": _owned_coins(state, leader, es.dry_run),
        "last_read_ms": existing_ls.last_read_ms if existing_ls else None,
        "effective": es,
    }


def _owned_coins(state: EngineState, leader: str, dry_run: bool) -> List[str]:
    rows = state.all_dry_copies() if dry_run else state.all_copies()
    return sorted(c.coin for c in rows if c.leader == leader)


# ── exits ───────────────────────────────────────────────────────────────────

def _do_close(cy: _Cycle, coin: str, leader: str) -> bool:
    """Full reduce-only close. True only when we are flat. Contract v2:
    `close` is ok only when the position is flat afterwards, so a partial
    fill or an ambiguous result keeps the row and the caller retries (close
    is idempotent: HlVenue sizes it from a fresh read every call)."""
    state, out = cy.state, cy.out
    if cy.dry:
        state.delete_dry_copy(coin)
        _set_catch_up(state, coin, None)
        cy.event("intent", leader=leader, coin=coin, reason="would close", dry_run=True)
        out["closed"].append(coin)
        return True
    want = abs(_szi(cy.our_positions, coin))
    pos = dict(cy.our_positions.get(coin) or {})
    res = cy.venue.close(coin, cloid=new_cloid())
    if not _full(res, want):
        if _filled(res) > 0:
            _book_fill(state, cy.venue, leader, coin, pos, res, _filled(res), cy.now_ms)
            reason = f"close partially filled ({_filled(res):.6g} of {want:.6g}), retrying next cycle"
            cy.event("error", leader=leader, coin=coin, reason=reason)
        elif res.get("ambiguous"):
            reason = "close outcome unknown (request may not have reached HL), retrying next cycle"
        else:
            reason = f"close failed, retrying next cycle: {res.get('error')}"
        cy.skip(coin, reason)
        return False
    _book_fill(state, cy.venue, leader, coin, pos, res, _close_size(res, want), cy.now_ms)
    state.delete_copy(coin)
    _set_catch_up(state, coin, None)
    cy.our_positions.pop(coin, None)
    out["closed"].append(coin)
    cy.event("close", leader=leader, coin=coin)
    return True


def _do_reduce(cy: _Cycle, coin: str, leader: str, prev: float, cur: float,
               pending_reduces: Dict[str, Any]) -> Tuple[bool, float]:
    """Returns `(ok, retry_prev)`. On failure the caller freezes the
    leader's last-seen size at `retry_prev` so the diff re-fires next cycle.
    That is `prev` for a plain failure. For a PARTIAL fill it is a synthetic
    size chosen so next cycle's fraction, applied to our real (already partly
    reduced) size, takes off exactly the part that did not fill. Reusing
    `prev` would take the full fraction off again.

    Never bumped to the exchange minimum. Under the floor with a remainder
    above it: skipped and left to accumulate (prev stays frozen, so his next
    reduce adds to the fraction). Remainder under the floor: full close."""
    state, venue, out = cy.state, cy.venue, cy.out
    frac = (abs(prev) - abs(cur)) / abs(prev)
    mid = venue.mid(coin)
    if mid <= 0:
        cy.skip(coin, "no mid")
        return False, prev

    if cy.dry:
        dc = state.get_dry_copy(coin)
        size_now = abs(dc.size)
    else:
        size_now = abs(_szi(cy.our_positions, coin))

    reduce_size = size_now * frac
    remainder_usd = (size_now - reduce_size) * mid
    if remainder_usd < HL_MIN_ORDER_USD:
        ok = _do_close(cy, coin, leader)
        if not ok:
            out["skipped"].setdefault(coin, "close failed, retrying next cycle")
        return ok, prev
    if reduce_size * mid < HL_MIN_ORDER_USD:
        cy.skip(coin, f"reduce ${reduce_size * mid:.2f} under the ${HL_MIN_ORDER_USD} minimum, "
                      f"accumulating until it is not")
        return False, prev

    if cy.dry:
        is_buy = dc.size < 0
        dc.size += reduce_size if is_buy else -reduce_size
        state.put_dry_copy(dc)
        cy.event("intent", leader=leader, coin=coin, reason=f"would reduce frac={frac:.4f}",
                 dry_run=True)
        out["reduced"].append(coin)
        return True, prev

    is_buy = _szi(cy.our_positions, coin) < 0
    pos = dict(cy.our_positions.get(coin) or {})
    order_size = venue.size_for(coin, reduce_size * mid, mid)
    cloid = new_cloid()
    res = venue.market(coin, is_buy, order_size, mid, reduce_only=True, cloid=cloid,
                       max_slippage_pct=cy.settings.for_leader(leader).max_slippage_pct)
    if _filled(res) > 0 or (_full(res, order_size) and "filled_sz" not in res):
        _book_fill(state, venue, leader, coin, pos, res,
                   _filled(res) if "filled_sz" in res else order_size, cy.now_ms)
    if _full(res, order_size):
        out["reduced"].append(coin)
        cy.event("reduce", leader=leader, coin=coin, reason=f"frac={frac:.4f}")
        return True, prev
    filled = _filled(res)
    if filled > 0:
        out["reduced"].append(coin)
        cy.event("reduce", leader=leader, coin=coin,
                 reason=(f"frac={frac:.4f} partial fill {filled:.6g} of {order_size:.6g}, "
                         f"rest retried next cycle"))
        cy.skip(coin, "reduce partially filled, retrying the rest next cycle")
        return False, _retry_prev(prev, cur, size_now, order_size, size_now - filled)
    if res.get("ambiguous"):
        # Unknown whether it filled. Never re-send blind: park it, resolve
        # next cycle from order_status + our real size (`_resolve_pending`).
        pending_reduces[coin] = {"cloid": cloid, "leader": leader, "prev": prev, "cur": cur,
                                 "size_before": size_now, "order_size": order_size,
                                 "sent_ms": cy.now_ms, "szi": float(pos.get("szi") or 0.0),
                                 "entry_px": float(pos.get("entry_px") or 0.0)}
        state.set_kv(_PENDING_REDUCES_KEY, pending_reduces)
        cy.skip(coin, "reduce outcome unknown, resolving next cycle")
        cy.event("error", leader=leader, coin=coin, reason="reduce outcome unknown, resolving next cycle")
        return False, prev
    cy.skip(coin, f"reduce failed, retrying next cycle: {res.get('error')}")
    return False, prev


def _retry_prev(prev: float, cur: float, size_before: float, order_size: float,
                size_after: float) -> float:
    """Leader size to freeze so next cycle reduces `size_after` down to the
    intended target `size_before - order_size`:
    (|p'| - |cur|) / |p'| == frac_left  =>  |p'| = |cur| / (1 - frac_left)."""
    remaining = order_size - (size_before - size_after)
    if remaining <= 0:
        return cur                                   # nothing left: settled
    if size_after <= 0 or remaining >= size_after:
        return prev                                  # degenerate: re-evaluate from scratch
    frac_left = remaining / size_after
    p = abs(cur) / (1 - frac_left)
    return p if prev > 0 else -p


# ── entries ─────────────────────────────────────────────────────────────────

def _open_or_add(cy: _Cycle, es: Settings, coin: str, leader: str, cur: float, prev: float,
                 lp: Dict[str, Any], his_equity: float, mid: float, ignored: Set[str],
                 copy: Optional[Copy], is_long: bool, direction: str) -> str:
    """`copy` is this leader's existing copy/shadow-copy row for `coin`, or
    None for a fresh open. `es` is this leader's EFFECTIVE settings.
    `is_long` is OUR side (his side, inverted for a counter `direction`).
    Sizes are direction-blind: every notional is |size| x price.
    Returns "done", "skip" or "retry" (the caller freezes his size)."""
    state, venue, dry = cy.state, cy.venue, cy.dry
    if copy is None:
        if _szi(cy.our_positions, coin) != 0.0 and state.get_copy(coin) is None:
            ignored.add(coin)
            cy.skip(coin, "not ours: a real position exists in this coin we did not open")
            return "skip"
        current_open = len(state.all_dry_copies()) if dry else len(state.all_copies())
        if current_open >= es.max_open_copies:
            ignored.add(coin)
            cy.skip(coin, f"max_open_copies reached ({es.max_open_copies})")
            return "skip"

    coin_max = venue.max_leverage(coin)
    if coin_max <= 0:
        # 0 means "unknown" -- never fabricate a leverage. Pending, re-checked.
        if copy is None:
            ignored.discard(coin)
        cy.skip(coin, f"unknown max leverage for {coin}")
        return "skip"
    allocation = es.sizing_mode == SizingMode.allocation
    lev = sizing.exchange_leverage(es, float(lp.get("lev") or 1.0), coin_max)
    if allocation and copy is not None:
        lev = max(1, int(copy.leverage))     # an add runs at the copy's own leverage
    his_added_ntl = (abs(cur) - abs(prev)) * float(lp.get("entry_px") or 0.0)

    scale = 1.0
    if allocation and es.small_account_mode == SmallAccountMode.concentrate:
        conc = _concentrate_scale(cy, es, leader, coin, his_equity)
        if conc is None:
            if copy is None:
                ignored.add(coin)
            cy.skip(coin, f"concentrate: his {coin} slice is under the ${HL_MIN_ORDER_USD} minimum, "
                          f"the allocation goes to his bigger positions")
            return "skip"
        scale = conc

    if copy is None:
        ntl = sizing.open_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders, lev,
                                   cy.lead_gross)
    elif prev == 0.0:
        # A copy exists but his last-seen size is flat: there is no fraction
        # to scale by (dividing by it crashed every cycle once). Proportional
        # and allocation size off his added notional alone; the fixed modes
        # have nothing sane to scale and skip the add.
        if es.sizing_mode not in (SizingMode.proportional, SizingMode.allocation):
            cy.skip(coin, "add skipped: copy exists but his previous size is flat (no fraction to scale)")
            return "skip"
        ntl = sizing.add_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders, 0.0, 0.0,
                                  cy.lead_gross, lev)
    else:
        cur_size = abs(state.get_dry_copy(coin).size) if dry else abs(_szi(cy.our_positions, coin))
        his_frac_added = (abs(cur) - abs(prev)) / abs(prev)
        ntl = sizing.add_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders,
                                  cur_size * mid, his_frac_added, cy.lead_gross, lev)
    return _execute_entry(cy, es, coin, leader, is_long, ntl * scale, lev, mid, copy, ignored, cur,
                          direction=direction)


def _concentrate_scale(cy: _Cycle, es: Settings, leader: str, coin: str,
                       his_equity: float) -> Optional[float]:
    """small_account_mode concentrate, on his book as it is now: the
    renormalization factor for `coin`, or None when `coin` is not in the
    eligible set. Coins we already copy for him are always eligible (they
    stay copied until he exits). Same `sizing.concentrate` the preview uses."""
    pos = cy.lead_pos
    levs = {c: max(1, sizing.exchange_leverage(es, float(p.get("lev") or 1.0),
                                               cy.venue.max_leverage(c)))
            for c, p in pos.items()}
    ntl = {c: sizing.his_notional(p) for c, p in pos.items()}
    base = sizing.base_slices(ntl, his_equity, es.allocation_usd, es.exposure_mode, levs)
    rows = cy.state.all_dry_copies() if cy.dry else cy.state.all_copies()
    held = {c.coin for c in rows if c.leader == leader}
    eligible, scale = sizing.concentrate(base, ntl, held)
    return scale if coin in eligible else None


def _held_entry_notional(cy: _Cycle, coin: str) -> float:
    """Our copy's size in this coin at its entry price (not mark, so price moves
    don't open room for more adds)."""
    pos = cy.our_positions.get(coin) or {}
    try:
        return abs(float(pos.get("szi") or 0.0)) * float(pos.get("entry_px") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _leader_margin(cy: _Cycle, leader: str) -> float:
    """Margin this leader's copies hold now: |size| x mark / leverage per
    copy, plus (live) the margin of orders sent earlier this cycle, which
    the start-of-cycle account read cannot show. Dry run sizes its shadow
    copies at mid; they are updated in place, so nothing is added."""
    total = 0.0
    if cy.dry:
        for dc in cy.state.all_dry_copies():
            if dc.leader == leader:
                total += abs(dc.size) * cy.venue.mid(dc.coin) / max(1, dc.leverage)
        return total
    for c in cy.state.all_copies():
        if c.leader != leader:
            continue
        szi = _szi(cy.our_positions, c.coin)
        if not szi:
            continue
        total += abs(szi) * _mark_px(cy.our_positions, cy.raw_positions, c.coin) / max(1, c.leverage)
    return total + cy.alloc_spent.get(leader, 0.0)


def _mark_px(positions: Dict[str, Any], raw_positions: Dict[str, Any], coin: str) -> float:
    szi = _szi(positions, coin)
    raw = raw_positions.get(coin) or {}
    pv = _float_or_none(raw.get("positionValue"))
    if pv is not None and szi:
        return abs(pv / szi)
    return float((positions.get(coin) or {}).get("entry_px") or 0.0)


def _liquidity_cap(cy: _Cycle, es: Settings, coin: str, is_buy: bool) -> Optional[float]:
    """`sizing.liquidity_cap` from live reads; None when either read failed
    (or the venue does not implement them yet)."""
    try:
        stats = cy.venue.market_stats(coin)
        depth = cy.venue.depth_usd(coin, is_buy, es.max_slippage_pct)
    except Exception:
        logger.warning("liquidity reads failed for %s", coin, exc_info=True)
        return None
    vol = _float_or_none((stats or {}).get("day_volume_usd")) if stats else None
    return sizing.liquidity_cap(vol, _float_or_none(depth), es.max_order_volume_pct)


def _execute_entry(cy: _Cycle, es: Settings, coin: str, leader: str, is_long: bool, ntl: float,
                   lev: int, mid: float, copy: Optional[Copy], ignored: Set[str], his_szi: float,
                   catch_up: bool = False, direction: str = "copy") -> str:
    """Caps, minimum, liquidity split, then the order. In this order:
    margin room (available x lev x 0.95), the allocation cap (allocation
    wallets: total wallet margin <= allocation_usd x 1.02), the bump (not for
    a catch-up remainder), the $10.50 minimum, then the liquidity cap: what
    does not fit is carried in kv `catch_up` and sent over the next cycles
    (`_catch_up`) until filled or he changes the position."""
    state, venue, out, dry = cy.state, cy.venue, cy.out, cy.dry
    action = "add" if copy is not None else "open"
    dex = coin.split(":", 1)[0] if ":" in coin else ""
    room = max(0.0, float(cy.available.get(dex, 0.0))) * lev * 0.95
    ntl = min(ntl, room)
    alloc_room: Optional[float] = None
    trimmed = False
    if es.sizing_mode == SizingMode.allocation:
        alloc_room = sizing.allocation_room_ntl(es, _leader_margin(cy, leader), lev)
        trimmed = ntl > alloc_room
        ntl = min(ntl, alloc_room)
    # Fixed modes: one copy is ONE fixed-size position. His adds may top it up
    # to that size (an open that was trimmed, partially filled or split), never
    # past it. Without this cap, dozens of tiny adds each bumped to $10.50 grew
    # a $1-margin copy to $126 of margin and one liquidation took the account to
    # -127% (found by the discovery sim, 2026-10-05).
    fixed_cap = sizing.fixed_copy_cap_ntl(es, lev)
    if copy is not None and fixed_cap is not None:
        held = _held_entry_notional(cy, coin)
        allowed = max(0.0, fixed_cap - held)
        if ntl > allowed:
            trimmed = True
            ntl = allowed
        if allowed < HL_MIN_ORDER_USD:
            if catch_up:
                _set_catch_up(state, coin, None)
            cy.skip(coin, f"add capped: copy already at its fixed size (${held:,.2f} of ${fixed_cap:,.2f})")
            return "skip"
    if not catch_up:
        ntl = sizing.bump(ntl, es)
    if copy is not None and fixed_cap is not None and ntl > allowed + 1e-9:
        cy.skip(coin, f"add capped: rounding up to ${ntl:.2f} would pass the copy's fixed size")
        return "skip"
    if ntl < HL_MIN_ORDER_USD:
        if copy is None:
            ignored.add(coin)
        if trimmed:
            reason = (f"allocation full: the ${es.allocation_usd:,.2f} wallet has ${ntl:.2f} of room, "
                      f"under the ${HL_MIN_ORDER_USD} minimum")
        else:
            reason = f"copy ${ntl:.2f} under the ${HL_MIN_ORDER_USD} minimum"
        if catch_up:
            _set_catch_up(state, coin, None)
        cy.skip(coin, reason)
        return "skip"
    if ntl > room:
        # min_order_bump rounded it up past the margin we actually have.
        if copy is None:
            ignored.add(coin)
        cy.skip(coin, f"copy ${ntl:.2f} needs more margin than available (room ${room:.2f})")
        return "skip"
    if alloc_room is not None and ntl > alloc_room + 1e-9:
        if copy is None:
            ignored.add(coin)
        cy.skip(coin, f"allocation full: bumping to ${ntl:.2f} would exceed the "
                      f"${es.allocation_usd:,.2f} allocation")
        return "skip"

    cap = _liquidity_cap(cy, es, coin, is_long)
    send, carry, why = sizing.split_order(ntl, cap)
    if why:
        cy.skip(coin, why)
        return "retry" if not catch_up else "skip"
    ntl = send
    split_note = (f"split: ${send:,.2f} now, ${carry:,.2f} over the next cycles "
                  f"(liquidity cap ${cap:,.2f})" if carry > 0 and cap is not None else None)
    if catch_up:
        split_note = f"catch-up: ${send:,.2f}" + (f", ${carry:,.2f} still to go" if carry > 0 else "")

    actual_cross = es.margin_mode == MarginMode.cross and not venue.is_isolated_only(coin)
    side = "long" if is_long else "short"

    if dry:
        cy.event("intent", leader=leader, coin=coin, side=side, notional_usd=round(ntl, 2),
                 leverage=lev, reason=f"would {action}" + (f" ({split_note})" if split_note else ""),
                 dry_run=True)
        size_delta = venue.size_for(coin, ntl, mid)
        signed_delta = size_delta if is_long else -size_delta
        if copy is None:
            state.put_dry_copy(DryCopy(coin, leader, cy.now_ms, lev, actual_cross,
                                       es.sizing_mode.value, signed_delta, direction=direction))
            out["opened"].append(coin)
        else:
            dc = state.get_dry_copy(coin)
            dc.size += signed_delta
            state.put_dry_copy(dc)
            out["added"].append(coin)
        _spend_margin(cy, dex, ntl / lev)
        _after_entry(cy, coin, leader, is_long, his_szi, carry)
        return "done"

    if copy is None:
        lev_res = venue.set_leverage(coin, lev, actual_cross)
        if not lev_res.get("ok"):
            ignored.add(coin)
            cy.skip(coin, "set_leverage failed")
            return "skip"

    size = venue.size_for(coin, ntl, mid)
    cloid = new_cloid()
    if copy is None:
        # Pending row BEFORE the order: a crash or a timeout after the order
        # reaches HL must still leave a row, or the position would be "not
        # ours" forever and copycat would never close it.
        state.put_copy(Copy(coin, leader, cy.now_ms, lev, actual_cross, es.sizing_mode.value,
                            pending_cloid=cloid, direction=direction))
    res = venue.market(coin, is_long, size, mid, cloid=cloid, max_slippage_pct=es.max_slippage_pct)
    filled = _filled(res)
    if not res.get("ok") and filled <= 0:
        if res.get("ambiguous"):
            reason = f"{action} outcome unknown (request may not have reached HL), resolving next cycle"
            cy.skip(coin, reason)
            cy.event("error", leader=leader, coin=coin, reason=reason)
            if catch_up:
                _set_catch_up(state, coin, None)   # never re-send blind
            return "skip"                # an open keeps its pending row; an add is not re-sent
        if copy is None:
            state.delete_copy(coin)
            ignored.add(coin)
        cy.skip(coin, f"order rejected: {res.get('error')}")
        return "skip"

    # Filled, fully or partly. Nothing stores an assumed size: every later
    # add/reduce reads OUR real szi from the next account read, so a partial
    # fill only means this copy is smaller than intended. The event records
    # what actually filled so the feed never overstates exposure. The unfilled
    # part joins the catch-up.
    notes = [n for n in (split_note,) if n]
    if _partial(res, size):
        px = float(res.get("avg_px") or mid)
        notes.append(f"partial fill {filled:.6g} of {size:.6g}")
        short = ntl - filled * px
        ntl = filled * px
        if short >= HL_MIN_ORDER_USD:
            carry += short
    _spend_margin(cy, dex, ntl / lev)
    cy.alloc_spent[leader] = cy.alloc_spent.get(leader, 0.0) + ntl / lev
    open_fee = fill_fee_usd(res, ntl)
    if open_fee:
        state.book_pnl(leader, -open_fee, open_fee, cy.now_ms)
    if copy is None:
        state.promote_copy(coin)
        out["opened"].append(coin)
    else:
        # An add never re-leverages or re-records the copy row.
        out["added"].append(coin)
    if direction == "counter" and copy is None:
        notes.insert(0, "counter: opposite of his side")
    cy.event(action, leader=leader, coin=coin, side=side, notional_usd=round(ntl, 2),
             leverage=lev, reason="; ".join(notes) or None)
    _after_entry(cy, coin, leader, is_long, his_szi, carry)
    return "done"


def _after_entry(cy: _Cycle, coin: str, leader: str, is_long: bool, his_szi: float,
                 carry: float) -> None:
    cy.entry_coins.add(coin)
    if carry >= HL_MIN_ORDER_USD:
        if coin not in cy.out["split"]:
            cy.out["split"].append(coin)
        _set_catch_up(cy.state, coin, {"leader": leader, "remaining_usd": round(carry, 6),
                                       "his_szi": his_szi, "is_long": is_long,
                                       "since_ms": cy.now_ms})
    else:
        _set_catch_up(cy.state, coin, None)


def _set_catch_up(state: EngineState, coin: str, entry: Optional[Dict[str, Any]]) -> None:
    cu = state.get_kv(_CATCH_UP_KEY)
    cu = cu if isinstance(cu, dict) else {}
    if entry is None:
        if coin not in cu:
            return
        cu.pop(coin, None)
    else:
        cu[coin] = entry
    state.set_kv(_CATCH_UP_KEY, cu)


def _catch_up(cy: _Cycle, leader: str, es: Settings, is_orphan: bool, now_pos: Dict[str, Any],
              retry: Dict[str, float]) -> None:
    """Send the next slice of every liquidity-split entry of this leader.
    Dropped once he changes that position (the diff already mirrored the
    change), our copy is gone, or the leader is an orphan. Paused (kept)
    while entries are blocked, the mid is missing or worse than his entry
    by more than max_worse_entry_pct. Never in the same cycle as an entry
    on that coin."""
    cu = cy.state.get_kv(_CATCH_UP_KEY)
    if not isinstance(cu, dict) or not cu:
        return
    for coin, e in sorted(cu.items()):
        if e.get("leader") != leader or coin in cy.entry_coins or coin in retry:
            continue
        his = _szi(now_pos, coin)
        copy = cy.state.get_dry_copy(coin) if cy.dry else cy.state.get_copy(coin)
        if (is_orphan or his != float(e.get("his_szi") or 0.0) or copy is None
                or copy.leader != leader):
            _set_catch_up(cy.state, coin, None)
            continue
        if not cy.dry and (copy.pending_cloid or not _szi(cy.our_positions, coin)):
            continue
        if not cy.entries_ok:
            cy.skip(coin, "catch-up paused: entries blocked" if cy.settings.enabled
                    else "catch-up paused: disabled")
            continue
        if es.paused:
            cy.skip(coin, "catch-up paused: paused")
            continue
        if not sizing.coin_allowed(es, coin):
            cy.skip(coin, f"catch-up paused: filtered: {coin}")
            continue
        is_long = sizing.our_is_long(his, copy.direction)   # the copy's own direction
        mid = cy.venue.mid(coin)
        if mid <= 0:
            cy.skip(coin, "no mid")
            continue
        entry_px = float((now_pos.get(coin) or {}).get("entry_px") or 0.0)
        side = "long" if is_long else "short"
        if not sizing.worse_entry_ok(side, mid, entry_px, es.max_worse_entry_pct):
            cy.skip(coin, f"catch-up paused: mid {mid:.6g} worse than entry {entry_px:.6g} by more "
                          f"than {es.max_worse_entry_pct:.1f}%")
            continue
        _execute_entry(cy, es, coin, leader, is_long, float(e.get("remaining_usd") or 0.0),
                       max(1, int(copy.leverage)), mid, copy, set(), his, catch_up=True,
                       direction=copy.direction)


# ── cycle-start reconciles ──────────────────────────────────────────────────

def _resolve_pending(cy: _Cycle) -> None:
    """Settle orders whose outcome was unknown last cycle (ambiguous result,
    or the process died between writing the pending row and the result).

    Opens: holding the coin now means it filled (fully or partly: HL reports
    a partly filled IOC as "canceled", so the status alone never decides) ->
    promote the row. Else ask HL by cloid; unsettled (None = read failed,
    "open", or "unknown" within `_UNKNOWN_GRACE_MS` of sending, since HL may
    not have processed it yet) -> wait; settled with no position -> delete
    the row and ignore the coin while the leader holds it.

    Reduces: once HL has settled the cloid, re-derive what filled from OUR
    real size (size_before - size_now) and set the leader's frozen size so
    next cycle's diff takes off exactly what is still owed."""
    state, venue = cy.state, cy.venue
    for c in state.all_copies():
        if not c.pending_cloid:
            continue
        szi = _szi(cy.our_positions, c.coin)
        if szi:
            state.promote_copy(c.coin)
            raw = cy.our_positions.get(c.coin) or {}
            cy.event("open", leader=c.leader, coin=c.coin, side="long" if szi > 0 else "short",
                     notional_usd=round(abs(szi) * float(raw.get("entry_px") or 0.0), 2),
                     leverage=c.leverage, reason="confirmed after an ambiguous order result")
            continue
        st = venue.order_status(c.pending_cloid)
        if not _settled(st, c.opened_ms, cy.now_ms):
            cy.skip(c.coin, "open order outcome unknown, resolving", leader=c.leader)
            continue
        state.delete_copy(c.coin)
        _ignore_while_leader_holds(state, c.leader, c.coin)
        cy.event("skip", leader=c.leader, coin=c.coin,
                 reason=f"open did not fill (order status {st}), waiting for the leader to go flat")

    pending = state.get_kv(_PENDING_REDUCES_KEY) or {}
    if not pending:
        return
    for coin, p in list(pending.items()):
        st = venue.order_status(p["cloid"])
        if not _settled(st, int(p.get("sent_ms") or 0), cy.now_ms):
            continue
        size_after = abs(_szi(cy.our_positions, coin))
        ls = state.get_leader(p["leader"])
        if ls is not None:
            ls.last_positions[coin] = _retry_prev(p["prev"], p["cur"], p["size_before"],
                                                  p["order_size"], size_after)
            state.put_leader(ls)
        filled = max(0.0, p["size_before"] - size_after)
        if filled > 0:
            booked = ({"szi": p["szi"], "entry_px": p["entry_px"]} if p.get("entry_px")
                      else cy.our_positions.get(coin) or {})
            _book_fill(state, venue, p["leader"], coin, booked, {}, filled, cy.now_ms)
        cy.event("reduce" if filled > 0 else "skip", leader=p["leader"], coin=coin,
                 reason=f"ambiguous reduce settled ({st}): filled {filled:.6g} of {p['order_size']:.6g}")
        del pending[coin]
    state.set_kv(_PENDING_REDUCES_KEY, pending)


def _reconcile_vanished(cy: _Cycle) -> None:
    """Every confirmed `copies` row whose coin is missing from our account read.

    Runs every non-dry cycle, independent of whether the leader moved: HL
    liquidating our isolated copy while the leader sits still changes nothing
    on his side, so the per-leader diff alone would never notice and the row
    would linger as a ghost and count against `max_open_copies` forever.

    Two consecutive reads are required before a copy is forgotten: a copy on
    a HIP-3 dex that one degraded read omitted must not be dropped (a
    forgotten copy is "not ours" and never closed again). The second miss
    deletes the row, ignores the coin while the leader still holds it, and
    logs one `skip` event with the last liquidation price we saw."""
    state = cy.state
    pending = state.get_kv(_VANISH_PENDING_KEY)
    pending = pending if isinstance(pending, dict) else {}
    marks = state.get_kv(_MARKS_KEY)
    marks = marks if isinstance(marks, dict) else {}
    still_pending: Dict[str, int] = {}
    for c in state.all_copies():
        if c.pending_cloid or _szi(cy.our_positions, c.coin) != 0.0:
            continue
        if c.coin not in pending:
            still_pending[c.coin] = cy.now_ms
            continue
        state.delete_copy(c.coin)
        _ignore_while_leader_holds(state, c.leader, c.coin)
        liq = (marks.get(c.coin) or {}).get("liq_px")
        reason = (f"{VANISHED_REASON}, last liq px {liq:.6g}" if isinstance(liq, (int, float))
                  else f"{VANISHED_REASON}, last liq px unknown")
        cy.out["vanished"].append(c.coin)
        cy.event("skip", leader=c.leader, coin=c.coin, reason=reason)
    state.set_kv(_VANISH_PENDING_KEY, still_pending)


def _ignore_while_leader_holds(state: EngineState, leader: str, coin: str) -> None:
    """Add `coin` to the leader's ignored set iff his last-seen size on it is
    nonzero, so copycat does not re-enter his position midway. The ignore
    clears itself when he goes flat (see the diff loop). Ignoring a coin he
    is flat on would also ignore his next fresh open, so that never happens."""
    ls = state.get_leader(leader)
    if ls is None or not float(ls.last_positions.get(coin) or 0.0):
        return
    if coin not in ls.ignored:
        ls.ignored = sorted(set(ls.ignored) | {coin})
        state.put_leader(ls)


# ── emergency close-all ─────────────────────────────────────────────────────

def close_all(venue: Venue, state: EngineState, our_address: str, now_ms: int,
              log_event: LogEvent) -> Dict[str, Any]:
    """Reduce-only close of every row in the real `copies` table (pending
    rows included: `close` is a no-op on a flat coin). Driven by
    `data/close_all.flag` (see `engine.public.run_cycle`).

    Runs regardless of `dry_run`: the flag is an explicit user command to
    flatten real positions, and a `copies` row only exists for a position
    copycat really opened. `dry_copies` is cleared too. Positions that are
    "not ours" are never touched.

    A failed, ambiguous or partially filled close keeps its row and is
    reported in `remaining`; the caller keeps the flag so the next cycle
    retries. Returns `{"closed": [...], "failed": {coin: reason}, "remaining": n}`."""
    out: Dict[str, Any] = {"closed": [], "failed": {}, "remaining": 0}
    acct = venue.account_state(our_address) if our_address else None
    positions = (acct or {}).get("positions") or {}
    pending_reduces = state.get_kv(_PENDING_REDUCES_KEY) or {}
    for c in state.all_copies():
        want = abs(_szi(positions, c.coin))
        res = venue.close(c.coin, cloid=new_cloid())
        if _filled(res) > 0 and not _full(res, want):
            _book_fill(state, venue, c.leader, c.coin, positions.get(c.coin) or {}, res,
                       _filled(res), now_ms)
        if _full(res, want):
            _book_fill(state, venue, c.leader, c.coin, positions.get(c.coin) or {}, res,
                       _close_size(res, want), now_ms)
            _set_catch_up(state, c.coin, None)
            state.delete_copy(c.coin)
            pending_reduces.pop(c.coin, None)
            _ignore_while_leader_holds(state, c.leader, c.coin)
            out["closed"].append(c.coin)
            log_event(EngineEvent(ts_ms=now_ms, action="close", leader=c.leader, coin=c.coin,
                                  reason="close-all"))
            continue
        if _filled(res) > 0:
            reason = f"close-all: partially filled ({_filled(res):.6g} of {want:.6g}), retrying next cycle"
        elif res.get("ambiguous"):
            reason = "close-all: close outcome unknown, retrying next cycle"
        else:
            reason = f"close-all: close failed, retrying next cycle: {res.get('error')}"
        out["failed"][c.coin] = reason
        log_event(EngineEvent(ts_ms=now_ms, action="error", leader=c.leader, coin=c.coin,
                              reason=reason))
    state.set_kv(_PENDING_REDUCES_KEY, pending_reduces)
    state.clear_dry_copies()
    out["remaining"] = len(state.all_copies())
    return out


# ── per-wallet ledger, stop-one-wallet, wallet status fields ────────────────

def _close_size(res: Dict[str, Any], want: float) -> float:
    """Size a successful close took off: the venue's filled_sz when it
    reports one (0.0 = we were already flat), else what we held."""
    return _filled(res) if "filled_sz" in res else want


TAKER_FEE_BPS = float(os.environ.get("COPYCAT_TAKER_FEE_BPS", "4.5"))   # HL base tier taker


def fill_fee_usd(res: Dict[str, Any], notional_usd: float) -> float:
    """Fee for one fill: the one HL reported, else an estimate at the taker
    rate. HL order responses carry no fee, and every copy order is an IOC
    (taker), so the estimate is the right default; a volume-tier discount
    makes it a slight overstatement, which is the safe direction for PnL."""
    reported = _float_or_none(res.get("fee")) or _float_or_none(res.get("fee_usd"))
    if reported:
        return abs(reported)
    return abs(notional_usd) * TAKER_FEE_BPS / 10_000


def _book_fill(state: EngineState, venue: Venue, leader: str, coin: str, pos: Dict[str, Any],
               res: Dict[str, Any], size: float, now_ms: int) -> None:
    """Realized PnL of one reduce/close fill of OUR copy into the leader's
    ledger: `(fill px - our entry px) x size x side - fee`. Fill px is the
    order's avg_px, else the mid. Fee: what the result reports (`fee` /
    `fee_usd`), else the taker-rate estimate from `fill_fee_usd`. Our
    entry is the average entry from the account read before the order, so
    a partial reduce does not move it. Nothing is booked without a size,
    an entry or a price."""
    try:
        szi = float(pos.get("szi") or 0.0)
        entry = float(pos.get("entry_px") or 0.0)
    except (TypeError, ValueError):
        return
    if size <= 0 or not szi or entry <= 0:
        return
    px = _float_or_none(res.get("avg_px")) or 0.0
    if px <= 0:
        try:
            px = float(venue.mid(coin))
        except Exception:
            px = 0.0
    if px <= 0:
        logger.warning("no fill px or mid for %s, realized PnL not booked", coin)
        return
    fee = fill_fee_usd(res, px * size)
    sign = 1.0 if szi > 0 else -1.0
    state.book_pnl(leader, (px - entry) * size * sign - fee, fee, now_ms)


def _run_stop(cy: _Cycle, addr: str, close_positions: bool) -> bool:
    """Stop one wallet (`data/stop/<address>.flag`). True when done (the
    caller deletes the flag).

    close_positions false: nothing to do here; the wallet is an orphan now,
    its open copies keep following his exits.
    close_positions true: close every copy of this leader reduce-only, like
    close-all for one wallet and, like close-all, even in dry_run (an
    explicit user command to flatten real positions). A failed, partial or
    ambiguous close keeps the flag, so the next cycle retries until flat."""
    state, venue = cy.state, cy.venue
    if not close_positions:
        cy.event("skip", leader=addr, reason="wallet stopped: open copies follow his exits")
        return True
    pending_reduces = state.get_kv(_PENDING_REDUCES_KEY) or {}
    remaining = 0
    for c in state.all_copies():
        if c.leader != addr:
            continue
        want = abs(_szi(cy.our_positions, c.coin))
        pos = dict(cy.our_positions.get(c.coin) or {})
        res = venue.close(c.coin, cloid=new_cloid())
        if _full(res, want):
            _book_fill(state, venue, addr, c.coin, pos, res, _close_size(res, want), cy.now_ms)
            state.delete_copy(c.coin)
            pending_reduces.pop(c.coin, None)
            _set_catch_up(state, c.coin, None)
            _ignore_while_leader_holds(state, addr, c.coin)
            cy.our_positions.pop(c.coin, None)
            cy.out["closed"].append(c.coin)
            cy.event("close", leader=addr, coin=c.coin, reason=STOP_REASON)
            continue
        remaining += 1
        if _filled(res) > 0:
            _book_fill(state, venue, addr, c.coin, pos, res, _filled(res), cy.now_ms)
            reason = (f"{STOP_REASON}: close partially filled ({_filled(res):.6g} of {want:.6g}), "
                      f"retrying next cycle")
        elif res.get("ambiguous"):
            reason = f"{STOP_REASON}: close outcome unknown, retrying next cycle"
        else:
            reason = f"{STOP_REASON}: close failed, retrying next cycle: {res.get('error')}"
        cy.skip(c.coin, reason, leader=addr)
        cy.event("error", leader=addr, coin=c.coin, reason=reason)
    state.set_kv(_PENDING_REDUCES_KEY, pending_reduces)
    for dc in state.all_dry_copies():
        if dc.leader == addr:
            state.delete_dry_copy(dc.coin)
            _set_catch_up(state, dc.coin, None)
    if remaining:
        return False
    cy.event("skip", leader=addr, reason="wallet stopped")
    return True


def _fill_wallet_fields(state: EngineState, rows: List[Dict[str, Any]],
                        positions: List[CopyPosition], raw_positions: Dict[str, Any],
                        stopping: Set[str], configured: Set[str]) -> None:
    """The Trade page's per-wallet "position" on every LeaderStatus row:
    our copies of that leader only, from this cycle's real positions (the
    same rows as EngineStatus.positions, so they always agree), plus the
    ledger. Margin is HL's `marginUsed` when the read has it, else
    notional / leverage. An orphan's `effective` shows the allocation terms
    it last ran with (from the ledger), so a winding-down wallet still has
    its terms on screen."""
    agg: Dict[str, Dict[str, float]] = {}
    for p in positions:
        a = agg.setdefault(p.leader, {"n": 0, "margin": 0.0, "exposure": 0.0, "upnl": 0.0})
        a["n"] += 1
        a["exposure"] += abs(p.notional_usd)
        a["upnl"] += p.unrealized_pnl_usd
        mu = _float_or_none((raw_positions.get(p.coin) or {}).get("marginUsed"))
        a["margin"] += mu if mu is not None else abs(p.notional_usd) / max(1, p.leverage)
    for row in rows:
        addr = row["address"]
        a = agg.get(addr) or {"n": 0, "margin": 0.0, "exposure": 0.0, "upnl": 0.0}
        led = state.get_ledger(addr) or {}
        row.update({
            "open_copies": int(a["n"]), "margin_used_usd": round(a["margin"], 6),
            "exposure_usd": round(a["exposure"], 6), "unrealized_pnl_usd": round(a["upnl"], 6),
            "realized_pnl_usd": round(float(led.get("realized_pnl_usd") or 0.0), 6),
            "fees_usd": round(float(led.get("fees_usd") or 0.0), 6),
            "stopping": addr in stopping,
        })
        terms = led.get("terms") or {}
        if addr not in configured and terms.get("sizing_mode") == SizingMode.allocation.value:
            eff = row["effective"].model_dump(mode="json")
            eff.update({k: v for k, v in terms.items() if v is not None})
            row["effective"] = Settings.model_validate(eff)


# ── risk gates ──────────────────────────────────────────────────────────────

def _spend_margin(cy: "_Cycle", dex: str, margin_usd: float) -> None:
    """Charge an open/add's margin against this cycle's room. Under a shared
    pool (unified/portfolio margin) every dex key is the same money, so every
    key goes down; otherwise only that dex's own margin does."""
    keys = list(cy.available) if cy.shared_margin else [dex]
    for k in keys:
        cy.available[k] = float(cy.available.get(k, 0.0)) - margin_usd


def _update_day_pnl(state: EngineState, now_ms: int, equity_usd: float) -> float:
    """PnL since the UTC day's equity anchor. Re-anchors at the first cycle
    of a new UTC day. NOT adjusted for deposits/withdrawals: a mid-day
    transfer is read as PnL (see the README's daily loss section)."""
    today = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    anchor = state.get_kv("day_anchor")
    if not isinstance(anchor, dict) or anchor.get("day") != today:
        anchor = {"day": today, "equity_usd": equity_usd}
        state.set_kv("day_anchor", anchor)
    return equity_usd - float(anchor["equity_usd"])


def _halt_check(state: EngineState, settings: Settings, day_pnl_usd: float,
                log_event: LogEvent, now_ms: int) -> Optional[str]:
    """`daily_loss_limit_usd` is always <= 0 by the contract; 0 means off.
    Halting blocks entries only; exits never check this."""
    halted_reason: Optional[str] = None
    if settings.daily_loss_limit_usd < 0 and day_pnl_usd <= settings.daily_loss_limit_usd:
        halted_reason = (f"daily loss limit ${settings.daily_loss_limit_usd:.2f} hit "
                         f"(day PnL ${day_pnl_usd:.2f})")
    was_halted = bool(state.get_kv("halted") or False)
    is_halted = halted_reason is not None
    if is_halted and not was_halted:
        log_event(EngineEvent(ts_ms=now_ms, action="halt", reason=halted_reason))
    elif was_halted and not is_halted:
        log_event(EngineEvent(ts_ms=now_ms, action="resume",
                              reason="day PnL back above the daily loss limit"))
    state.set_kv("halted", is_halted)
    return halted_reason


# ── status ──────────────────────────────────────────────────────────────────

def _build_positions(state: EngineState, our_account: Dict[str, Any],
                     now_ms: int = 0) -> List[CopyPosition]:
    """Always from the REAL `copies` table, regardless of `dry_run`: a
    dry-run shadow position is not real and is never surfaced. A copy that
    is missing from this read (liquidated, closed by hand, pending vanish
    confirmation, or a pending open that did not fill) is skipped: the UI
    never shows a zero-size ghost row. Also persists each copy's last seen
    liquidation/mark price for the "vanished" event."""
    raw_positions = our_account.get("raw_positions") or {}
    positions = our_account.get("positions") or {}
    out: List[CopyPosition] = []
    marks = state.get_kv(_MARKS_KEY)
    marks = marks if isinstance(marks, dict) else {}
    copies = state.all_copies()
    for c in copies:
        raw = raw_positions.get(c.coin) or {}
        pos = positions.get(c.coin) or {}
        szi = float(pos.get("szi") or 0.0)
        if szi == 0.0:
            continue
        entry_px = float(pos.get("entry_px") or raw.get("entryPx") or 0.0)
        mark_px = 0.0
        pv = raw.get("positionValue")
        if pv is not None:
            try:
                mark_px = abs(float(pv) / szi)
            except (TypeError, ValueError, ZeroDivisionError):
                mark_px = 0.0
        notional_usd = abs(szi) * (mark_px or entry_px)
        liq_px = _float_or_none(raw.get("liquidationPx"))
        marks[c.coin] = {"liq_px": liq_px, "mark_px": mark_px or None, "szi": szi, "ts_ms": now_ms}
        out.append(CopyPosition(
            coin=c.coin, leader=c.leader, side="long" if szi >= 0 else "short", size=szi,
            entry_px=entry_px, mark_px=mark_px, notional_usd=round(notional_usd, 4),
            leverage=c.leverage, is_cross=c.is_cross,
            unrealized_pnl_usd=float(raw.get("unrealizedPnl") or 0.0),
            liquidation_px=liq_px,
            opened_ms=c.opened_ms, sizing_mode=SizingMode(c.sizing_mode),
        ))
    live = {c.coin for c in copies}
    state.set_kv(_MARKS_KEY, {k: v for k, v in marks.items() if k in live})
    return out


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
