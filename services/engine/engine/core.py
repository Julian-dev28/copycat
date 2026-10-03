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
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from contracts.models import (
    CopyPosition,
    EngineEvent,
    HL_MIN_ORDER_USD,
    LeaderStatus,
    MarginMode,
    Settings,
    SizingMode,
)
from contracts.venue import Venue

from . import sizing
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

    def event(self, action: str, **kw: Any) -> None:
        self.log_event(EngineEvent(ts_ms=self.now_ms, action=action, **kw))

    def skip(self, coin: str, reason: str) -> None:
        self.out["skipped"][coin] = reason


def run_cycle(settings: Settings, venue: Venue, state: EngineState, our_address: str,
              now_ms: int, log_event: LogEvent) -> Dict[str, Any]:
    """One full cycle. Everything it does goes through `venue` and `state`.
    Returns a plain summary dict; `engine.public.run_cycle` wraps this with
    settings reload, the SQLite `EngineStatus` snapshot and the one-line log.
    """
    out: Dict[str, Any] = {
        "opened": [], "added": [], "reduced": [], "closed": [], "skipped": {}, "vanished": [],
        "leaders_ok": 0, "leaders_total": 0,
        "equity_usd": None, "available_margin_usd": None, "day_pnl_usd": None,
        "halted_reason": None, "enabled": settings.enabled, "dry_run": settings.dry_run,
        "positions": [], "leaders": [],
    }
    cy = _Cycle(settings, venue, state, now_ms, log_event, out)

    last_dry = state.get_kv(_LAST_DRY_RUN_KEY)
    if last_dry is not None and bool(last_dry) != settings.dry_run:
        # The shadow book only means something within one dry-run stretch.
        state.clear_dry_copies()
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

    if not cy.dry:
        _resolve_pending(cy)
        _reconcile_vanished(cy)

    configured = list(settings.leaders)
    configured_set = set(configured)
    orphans = sorted(a for a in state.leader_addresses() if a not in configured_set)
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
    out["leaders"] = [LeaderStatus(**r) for r in leader_rows]
    _log_skip_changes(state, out["skipped"], now_ms, log_event, settings.dry_run)
    return out


# ── one leader ──────────────────────────────────────────────────────────────

def _run_leader(cy: _Cycle, leader: str, es: Settings, is_orphan: bool) -> Dict[str, Any]:
    state, venue, out = cy.state, cy.venue, cy.out
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
    lstate = state.get_leader(leader)
    if lstate is None:
        if cy.settings.only_new_positions:
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
                last[c.coin] = 1.0 if _szi(cy.our_positions, c.coin) > 0 else -1.0
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
    mid = venue.mid(coin)
    if mid <= 0:
        cy.skip(coin, "no mid")
        retry[coin] = prev
        return
    entry_px = float(lp.get("entry_px") or 0.0)
    side = "long" if cur > 0 else "short"
    if not sizing.worse_entry_ok(side, mid, entry_px, es.max_worse_entry_pct):
        cy.skip(coin, f"mid {mid:.6g} worse than entry {entry_px:.6g} by more than "
                      f"{es.max_worse_entry_pct:.1f}%")
        retry[coin] = prev
        return
    _open_or_add(cy, es, coin, leader, cur, prev, lp, his_equity, mid, ignored, copy)


def _log_skip_changes(state: EngineState, skipped: Dict[str, str], now_ms: int,
                      log_event: LogEvent, dry_run: bool) -> None:
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
        leader = key.split(":", 1)[1] if key.startswith("leader:") else None
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
        cy.event("intent", leader=leader, coin=coin, reason="would close", dry_run=True)
        out["closed"].append(coin)
        return True
    want = abs(_szi(cy.our_positions, coin))
    res = cy.venue.close(coin, cloid=new_cloid())
    if not _full(res, want):
        if _filled(res) > 0:
            reason = f"close partially filled ({_filled(res):.6g} of {want:.6g}), retrying next cycle"
            cy.event("error", leader=leader, coin=coin, reason=reason)
        elif res.get("ambiguous"):
            reason = "close outcome unknown (request may not have reached HL), retrying next cycle"
        else:
            reason = f"close failed, retrying next cycle: {res.get('error')}"
        cy.skip(coin, reason)
        return False
    state.delete_copy(coin)
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
    order_size = venue.size_for(coin, reduce_size * mid, mid)
    cloid = new_cloid()
    res = venue.market(coin, is_buy, order_size, mid, reduce_only=True, cloid=cloid)
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
                                 "sent_ms": cy.now_ms}
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
                 copy: Optional[Copy]) -> None:
    """`copy` is this leader's existing copy/shadow-copy row for `coin`, or
    None for a fresh open. `es` is this leader's EFFECTIVE settings."""
    state, venue, out, dry = cy.state, cy.venue, cy.out, cy.dry
    if copy is None:
        if _szi(cy.our_positions, coin) != 0.0 and state.get_copy(coin) is None:
            ignored.add(coin)
            cy.skip(coin, "not ours: a real position exists in this coin we did not open")
            return
        current_open = len(state.all_dry_copies()) if dry else len(state.all_copies())
        if current_open >= es.max_open_copies:
            ignored.add(coin)
            cy.skip(coin, f"max_open_copies reached ({es.max_open_copies})")
            return

    coin_max = venue.max_leverage(coin)
    if coin_max <= 0:
        # 0 means "unknown" -- never fabricate a leverage. Pending, re-checked.
        if copy is None:
            ignored.discard(coin)
        cy.skip(coin, f"unknown max leverage for {coin}")
        return
    lev = sizing.exchange_leverage(es, float(lp.get("lev") or 1.0), coin_max)
    his_added_ntl = (abs(cur) - abs(prev)) * float(lp.get("entry_px") or 0.0)

    if copy is None:
        ntl = sizing.open_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders, lev)
    elif prev == 0.0:
        # A copy exists but his last-seen size is flat: there is no fraction
        # to scale by (dividing by it crashed every cycle once). Proportional
        # sizes off his added notional alone; the fixed modes have nothing
        # sane to scale and skip the add.
        if es.sizing_mode != SizingMode.proportional:
            cy.skip(coin, "add skipped: copy exists but his previous size is flat (no fraction to scale)")
            return
        ntl = sizing.add_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders, 0.0, 0.0)
    else:
        cur_size = abs(state.get_dry_copy(coin).size) if dry else abs(_szi(cy.our_positions, coin))
        his_frac_added = (abs(cur) - abs(prev)) / abs(prev)
        ntl = sizing.add_notional(es, his_added_ntl, his_equity, cy.equity_usd, cy.n_leaders,
                                  cur_size * mid, his_frac_added)

    dex = coin.split(":", 1)[0] if ":" in coin else ""
    room = max(0.0, float(cy.available.get(dex, 0.0))) * lev * 0.95
    ntl = min(ntl, room)
    ntl = sizing.bump(ntl, es)
    if ntl < HL_MIN_ORDER_USD:
        if copy is None:
            ignored.add(coin)
        cy.skip(coin, f"copy ${ntl:.2f} under the ${HL_MIN_ORDER_USD} minimum")
        return
    if ntl > room:
        # min_order_bump rounded it up past the margin we actually have.
        if copy is None:
            ignored.add(coin)
        cy.skip(coin, f"copy ${ntl:.2f} needs more margin than available (room ${room:.2f})")
        return

    actual_cross = es.margin_mode == MarginMode.cross and not venue.is_isolated_only(coin)
    side = "long" if cur > 0 else "short"
    action = "add" if copy is not None else "open"

    if dry:
        cy.event("intent", leader=leader, coin=coin, side=side, notional_usd=round(ntl, 2),
                 leverage=lev, reason=f"would {action}", dry_run=True)
        size_delta = venue.size_for(coin, ntl, mid)
        signed_delta = size_delta if cur > 0 else -size_delta
        if copy is None:
            state.put_dry_copy(DryCopy(coin, leader, cy.now_ms, lev, actual_cross,
                                       es.sizing_mode.value, signed_delta))
            out["opened"].append(coin)
        else:
            dc = state.get_dry_copy(coin)
            dc.size += signed_delta
            state.put_dry_copy(dc)
            out["added"].append(coin)
        _spend_margin(cy, dex, ntl / lev)
        return

    if copy is None:
        lev_res = venue.set_leverage(coin, lev, actual_cross)
        if not lev_res.get("ok"):
            ignored.add(coin)
            cy.skip(coin, "set_leverage failed")
            return

    size = venue.size_for(coin, ntl, mid)
    cloid = new_cloid()
    if copy is None:
        # Pending row BEFORE the order: a crash or a timeout after the order
        # reaches HL must still leave a row, or the position would be "not
        # ours" forever and copycat would never close it.
        state.put_copy(Copy(coin, leader, cy.now_ms, lev, actual_cross, es.sizing_mode.value,
                            pending_cloid=cloid))
    res = venue.market(coin, cur > 0, size, mid, cloid=cloid)
    filled = _filled(res)
    if not res.get("ok") and filled <= 0:
        if res.get("ambiguous"):
            reason = f"{action} outcome unknown (request may not have reached HL), resolving next cycle"
            cy.skip(coin, reason)
            cy.event("error", leader=leader, coin=coin, reason=reason)
            return                      # an open keeps its pending row; an add is not re-sent
        if copy is None:
            state.delete_copy(coin)
            ignored.add(coin)
        cy.skip(coin, f"order rejected: {res.get('error')}")
        return

    # Filled, fully or partly. Nothing stores an assumed size: every later
    # add/reduce reads OUR real szi from the next account read, so a partial
    # fill only means this copy is smaller than intended. The event records
    # what actually filled so the feed never overstates exposure.
    fill_note: Optional[str] = None
    if _partial(res, size):
        px = float(res.get("avg_px") or mid)
        fill_note = f"partial fill {filled:.6g} of {size:.6g}"
        ntl = filled * px
    _spend_margin(cy, dex, ntl / lev)
    if copy is None:
        state.promote_copy(coin)
        out["opened"].append(coin)
    else:
        # An add never re-leverages or re-records the copy row.
        out["added"].append(coin)
    cy.event(action, leader=leader, coin=coin, side=side, notional_usd=round(ntl, 2),
             leverage=lev, reason=fill_note)


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
            cy.skip(c.coin, "open order outcome unknown, resolving")
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
        if _full(res, want):
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
