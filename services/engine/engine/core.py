"""The copy cycle: diff every leader's positions against last cycle and
mirror the changes, one net position per coin across the whole book. Ported
from pathiel's `copycat_live.maybe_run` (sibling repo, commit ab2e800) onto
`contracts.models`/`contracts.venue` and SQLite state instead of pathiel's
JSON-file state and claims registry. The semantics below are the proven
ones from that file; see `services/engine/README.md` for the plain-English
rule set.

Kept, unchanged in spirit:
  - one leader owns a coin at a time (first to open it that cycle keeps it
    until OUR copy of it closes)
  - a leader read failure skips only that leader and never looks like him
    going flat
  - exits (reduce/close/flip) mirror regardless of `enabled` -- a copy
    already on the exchange must still follow the leader out. `dry_run` is
    a different axis: it blocks ALL writes, exits included (see
    `public.py` and the README)
  - a failed exit is retried every cycle until it succeeds (by freezing
    `last_positions[coin]` at the stale value so the diff keeps re-firing)
  - a flip (long<->short in one read) is a close then a fresh open
  - `max_worse_entry_pct` gates opens/adds only, and the skip is PENDING
    (re-checked every cycle), never permanent
  - `min_order_bump` only bumps a notional that is already close to the
    floor
  - orphan leaders (removed from `Settings.leaders` but still holding a
    copy) keep exiting, never get new exposure
  - "our copy vanished" (liquidated or closed by hand) stops mirroring that
    coin until the leader goes flat and reopens it

Changed for the standalone product (see services/engine/README.md for why):
  - no claims registry, no other books: a real position in a coin that is
    not in our own `copies` table is "not ours" -- never touched, never
    copied into
  - `daily_loss_limit_usd` / `max_open_copies` risk gates (pathiel had a
    cross-book mark-to-market grader instead; there is nothing to grade
    against here, it is the only book)
  - `dry_run`: real reads, no writes at all, `intent` events instead of
    orders, a separate shadow `dry_copies` table so a sequence of dry-run
    cycles still classifies open vs add vs reduce vs close correctly
    without ever touching the real `copies` table
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

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

LogEvent = Callable[[EngineEvent], None]


def run_cycle(settings: Settings, venue: Venue, state: EngineState, our_address: str,
              now_ms: int, log_event: LogEvent) -> Dict[str, Any]:
    """One full cycle. Pure with respect to `venue` and `state` only --
    everything it does goes through those two, nothing else is global.
    Returns a plain summary dict; `engine.public.run_cycle` wraps this with
    settings reload, the SQLite `EngineStatus` snapshot and the one-line log.
    """
    out: Dict[str, Any] = {
        "opened": [], "added": [], "reduced": [], "closed": [], "skipped": {},
        "leaders_ok": 0, "leaders_total": 0,
        "equity_usd": None, "available_margin_usd": None, "day_pnl_usd": None,
        "halted_reason": None, "enabled": settings.enabled, "dry_run": settings.dry_run,
        "positions": [], "leaders": [],
    }

    our_account = venue.account_state(our_address) if our_address else None
    if our_account is None:
        out["skipped"]["all"] = "our account read failed"
        log_event(EngineEvent(ts_ms=now_ms, action="error", reason="our account read failed"))
        return out

    equity_usd = float(our_account["equity_perp_usd"]) + float(our_account["spot_usdc"])
    out["equity_usd"] = equity_usd
    out["available_margin_usd"] = sum(float(v) for v in our_account["available"].values())
    if equity_usd <= 0:
        out["skipped"]["all"] = "degraded account read (equity <= 0)"
        log_event(EngineEvent(ts_ms=now_ms, action="error",
                               reason="degraded account read (equity <= 0)"))
        return out

    day_pnl_usd = _update_day_pnl(state, now_ms, equity_usd)
    out["day_pnl_usd"] = day_pnl_usd
    halted_reason = _halt_check(state, settings, day_pnl_usd, log_event, now_ms)
    out["halted_reason"] = halted_reason
    entries_ok = settings.enabled and halted_reason is None

    available = dict(our_account["available"])
    # Local copy: a coin we close this cycle is flat for the rest of it. Reading
    # the start-of-cycle snapshot made a flip (close, then fresh open) refuse
    # its own open as "not ours".
    our_positions = dict(our_account["positions"])

    configured = list(settings.leaders)
    configured_set = set(configured)
    orphans = sorted(a for a in state.leader_addresses() if a not in configured_set)
    order = configured + orphans
    out["leaders_total"] = len(order)
    n_leaders = max(1, len(configured))

    leader_rows: List[Dict[str, Any]] = []

    for leader in order:
        is_orphan = leader not in configured_set
        es = settings.for_leader(leader)
        lead_account = venue.account_state(leader)
        if lead_account is None:
            out["skipped"][f"leader:{leader}"] = "leader read failed"
            leader_rows.append(_failed_leader_row(state, leader, es))
            continue

        if es.include_spot_staked:
            extras = venue.extras(leader)
            if extras is None:
                out["skipped"][f"leader:{leader}"] = "extras read failed"
                leader_rows.append(_failed_leader_row(state, leader, es))
                continue
            his_equity = (float(lead_account["equity_perp_usd"]) + float(lead_account["spot_usdc"])
                          + float(extras["spot_other_usd"]) + float(extras["staked_hype_usd"]))
        else:
            his_equity = float(lead_account["equity_perp_usd"]) + float(lead_account["spot_usdc"])

        now_pos = lead_account["positions"]
        lstate = state.get_leader(leader)
        if lstate is None:
            if settings.only_new_positions:
                lstate = LeaderState(leader, {c: p["szi"] for c, p in now_pos.items()},
                                      sorted(now_pos.keys()), now_ms)
                state.put_leader(lstate)
                log_event(EngineEvent(
                    ts_ms=now_ms, action="baseline", leader=leader,
                    reason=("ignoring pre-existing: " + ",".join(sorted(now_pos.keys()))
                            if now_pos else "no pre-existing positions")))
                out["leaders_ok"] += 1
                leader_rows.append({"address": leader, "read_ok": True, "equity_usd": his_equity,
                                     "open_positions": len(now_pos), "owned_coins": [],
                                     "last_read_ms": now_ms, "effective": es})
                continue
            lstate = LeaderState(leader, {}, [], now_ms)

        last = lstate.last_positions
        ignored = set(lstate.ignored)
        retry: Dict[str, float] = {}

        for coin in sorted(set(last) | set(now_pos)):
            prev = float(last.get(coin) or 0.0)
            cur = float((now_pos.get(coin) or {}).get("szi") or 0.0)
            if prev == cur:
                continue
            flipped = bool(prev) and bool(cur) and (prev > 0) != (cur > 0)

            existing = state.get_dry_copy(coin) if settings.dry_run else state.get_copy(coin)
            if existing is not None and existing.leader != leader:
                out["skipped"][coin] = f"owned by leader {existing.leader}"
                continue

            if coin in ignored:
                if cur and not flipped:
                    continue
                ignored.discard(coin)
                if not cur:
                    continue
                prev = 0.0  # a flip, or a fresh nonzero value after un-ignoring, is a fresh open

            copy = existing

            if not settings.dry_run:
                mine = our_positions.get(coin)
                if copy is not None and not mine:
                    # Our real copy is gone (liquidated, closed by hand): stop
                    # mirroring this coin until the leader is flat on it again.
                    state.delete_copy(coin)
                    if cur:
                        ignored.add(coin)
                    out["skipped"][coin] = "our copy vanished"
                    continue

            if copy is not None and (not cur or flipped):
                ok = _do_close(venue, settings.dry_run, state, coin, leader, log_event, now_ms, out,
                               our_positions)
                if not ok:
                    out["skipped"][coin] = "close failed, retrying next cycle"
                    retry[coin] = prev
                    continue
                if not flipped:
                    continue
                copy, prev = None, 0.0

            if copy is not None and abs(cur) < abs(prev):
                ok = _do_reduce(venue, settings.dry_run, state, coin, leader, prev, cur,
                                 our_positions, log_event, now_ms, out)
                if not ok:
                    retry[coin] = prev
                    continue
            elif abs(cur) > abs(prev):
                lp = now_pos[coin]
                if is_orphan:
                    if copy is None and cur:
                        ignored.add(coin)
                    out["skipped"][coin] = "orphan leader: no new exposure"
                elif not entries_ok:
                    if copy is None and cur:
                        ignored.add(coin)
                    out["skipped"][coin] = "entries blocked" if settings.enabled else "disabled"
                else:
                    mid = venue.mid(coin)
                    if mid <= 0:
                        out["skipped"][coin] = "no mid"
                        retry[coin] = prev
                    else:
                        entry_px = float(lp.get("entry_px") or 0.0)
                        side = "long" if cur > 0 else "short"
                        if not sizing.worse_entry_ok(side, mid, entry_px, es.max_worse_entry_pct):
                            out["skipped"][coin] = (
                                f"mid {mid:.6g} worse than entry {entry_px:.6g} by more than "
                                f"{es.max_worse_entry_pct:.1f}%")
                            retry[coin] = prev
                        else:
                            _open_or_add(venue, es, state, coin, leader, cur, prev, lp,
                                         his_equity, equity_usd, n_leaders, available,
                                         settings.dry_run, mid, now_ms, log_event, ignored, out,
                                         our_positions, copy)

        new_last = {c: p["szi"] for c, p in now_pos.items()}
        for coin, frozen_prev in retry.items():
            new_last[coin] = frozen_prev
        state.put_leader(LeaderState(leader, new_last, sorted(ignored), now_ms))
        out["leaders_ok"] += 1
        leader_rows.append({
            "address": leader, "read_ok": True, "equity_usd": his_equity,
            "open_positions": len(now_pos),
            "owned_coins": _owned_coins(state, leader, settings.dry_run),
            "last_read_ms": now_ms, "effective": es,
        })

    out["positions"] = _build_positions(state, our_account)
    out["leaders"] = [LeaderStatus(**r) for r in leader_rows]
    _log_skip_changes(state, out["skipped"], now_ms, log_event, settings.dry_run)
    return out


_NUMBERS = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


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


def _do_close(venue: Venue, dry_run: bool, state: EngineState, coin: str, leader: str,
              log_event: LogEvent, now_ms: int, out: Dict[str, Any],
              our_positions: Dict[str, Any]) -> bool:
    if dry_run:
        state.delete_dry_copy(coin)
        log_event(EngineEvent(ts_ms=now_ms, action="intent", leader=leader, coin=coin,
                               reason="would close", dry_run=True))
        out["closed"].append(coin)
        return True
    res = venue.close(coin)
    if not res.get("ok"):
        return False
    state.delete_copy(coin)
    our_positions.pop(coin, None)
    out["closed"].append(coin)
    log_event(EngineEvent(ts_ms=now_ms, action="close", leader=leader, coin=coin))
    return True


def _do_reduce(venue: Venue, dry_run: bool, state: EngineState, coin: str, leader: str,
               prev: float, cur: float, our_positions: Dict[str, Any], log_event: LogEvent,
               now_ms: int, out: Dict[str, Any]) -> bool:
    frac = (abs(prev) - abs(cur)) / abs(prev)
    mid = venue.mid(coin)
    if mid <= 0:
        out["skipped"][coin] = "no mid"
        return False

    if dry_run:
        dc = state.get_dry_copy(coin)
        size_now = abs(dc.size)
    else:
        size_now = abs(float((our_positions.get(coin) or {}).get("szi") or 0.0))

    reduce_size = size_now * frac
    remainder_usd = (size_now - reduce_size) * mid
    if remainder_usd < HL_MIN_ORDER_USD:
        # The remainder would be dust under the exchange floor -- close fully instead.
        ok = _do_close(venue, dry_run, state, coin, leader, log_event, now_ms, out, our_positions)
        if not ok:
            out["skipped"][coin] = "close failed, retrying next cycle"
        return ok

    if dry_run:
        is_buy = dc.size < 0
        dc.size += reduce_size if is_buy else -reduce_size
        state.put_dry_copy(dc)
        log_event(EngineEvent(ts_ms=now_ms, action="intent", leader=leader, coin=coin,
                               reason=f"would reduce frac={frac:.4f}", dry_run=True))
        out["reduced"].append(coin)
        return True

    mine_szi = float((our_positions.get(coin) or {}).get("szi") or 0.0)
    is_buy = mine_szi < 0
    res = venue.market(coin, is_buy, venue.size_for(coin, reduce_size * mid, mid), mid,
                        reduce_only=True)
    if not res.get("ok"):
        out["skipped"][coin] = "reduce failed, retrying next cycle"
        return False
    out["reduced"].append(coin)
    log_event(EngineEvent(ts_ms=now_ms, action="reduce", leader=leader, coin=coin,
                           reason=f"frac={frac:.4f}"))
    return True


def _open_or_add(venue: Venue, es: Settings, state: EngineState, coin: str, leader: str,
                  cur: float, prev: float, lp: Dict[str, Any], his_equity: float,
                  our_equity: float, n_leaders: int, available: Dict[str, float],
                  dry_run: bool, mid: float, now_ms: int, log_event: LogEvent,
                  ignored: Set[str], out: Dict[str, Any], our_positions: Dict[str, Any],
                  copy: Optional[Copy]) -> None:
    """`copy` is this leader's existing copy/shadow-copy row for `coin`, or
    None for a fresh open. `es` is this leader's EFFECTIVE settings
    (`Settings.for_leader`)."""
    if copy is None:
        real_mine = our_positions.get(coin)
        real_szi = float((real_mine or {}).get("szi") or 0.0)
        if real_szi != 0.0 and state.get_copy(coin) is None:
            ignored.add(coin)
            out["skipped"][coin] = "not ours: a real position exists in this coin we did not open"
            return
        current_open = len(state.all_dry_copies()) if dry_run else len(state.all_copies())
        if current_open >= es.max_open_copies:
            ignored.add(coin)
            out["skipped"][coin] = f"max_open_copies reached ({es.max_open_copies})"
            return

    coin_max = venue.max_leverage(coin)
    if coin_max <= 0:
        # 0 means "unknown" (contracts.venue.Venue: "never silently 1") --
        # never fabricate a leverage to trade on. Pending, not permanent:
        # re-checked every cycle like a worse-entry skip, in case it was a
        # transient meta-cache miss on the hl side.
        if copy is None:
            ignored.discard(coin)
        out["skipped"][coin] = f"unknown max leverage for {coin}"
        return
    lev = sizing.exchange_leverage(es, float(lp.get("lev") or 1.0), coin_max)
    his_added_ntl = (abs(cur) - abs(prev)) * float(lp.get("entry_px") or 0.0)

    if copy is None:
        ntl = sizing.open_notional(es, his_added_ntl, his_equity, our_equity, n_leaders, lev)
    else:
        if dry_run:
            cur_size = abs(state.get_dry_copy(coin).size)
        else:
            cur_size = abs(float((our_positions.get(coin) or {}).get("szi") or 0.0))
        our_current_notional = cur_size * mid
        his_frac_added = (abs(cur) - abs(prev)) / abs(prev)
        ntl = sizing.add_notional(es, his_added_ntl, his_equity, our_equity, n_leaders,
                                   our_current_notional, his_frac_added)

    dex = coin.split(":", 1)[0] if ":" in coin else ""
    room = max(0.0, float(available.get(dex, 0.0))) * lev * 0.95
    ntl = min(ntl, room)
    ntl = sizing.bump(ntl, es)
    if ntl < HL_MIN_ORDER_USD:
        if copy is None:
            ignored.add(coin)
        out["skipped"][coin] = f"copy ${ntl:.2f} under the ${HL_MIN_ORDER_USD} minimum"
        return

    is_cross_requested = es.margin_mode == MarginMode.cross
    actual_cross = is_cross_requested and not venue.is_isolated_only(coin)
    side = "long" if cur > 0 else "short"
    action = "add" if copy is not None else "open"

    if dry_run:
        log_event(EngineEvent(ts_ms=now_ms, action="intent", leader=leader, coin=coin, side=side,
                               notional_usd=round(ntl, 2), leverage=lev,
                               reason=f"would {action}", dry_run=True))
        size_delta = venue.size_for(coin, ntl, mid)
        signed_delta = size_delta if cur > 0 else -size_delta
        if copy is None:
            state.put_dry_copy(DryCopy(coin, leader, now_ms, lev, actual_cross,
                                        es.sizing_mode.value, signed_delta))
            out["opened"].append(coin)
        else:
            dc = state.get_dry_copy(coin)
            dc.size += signed_delta
            state.put_dry_copy(dc)
            out["added"].append(coin)
        available[dex] = float(available.get(dex, 0.0)) - ntl / lev
        return

    if copy is None:
        lev_res = venue.set_leverage(coin, lev, actual_cross)
        if not lev_res.get("ok"):
            ignored.add(coin)
            out["skipped"][coin] = "set_leverage failed"
            return

    size = venue.size_for(coin, ntl, mid)
    res = venue.market(coin, cur > 0, size, mid)
    if not res.get("ok"):
        if copy is None:
            ignored.add(coin)
        out["skipped"][coin] = f"order rejected: {res.get('error')}"
        return

    available[dex] = float(available.get(dex, 0.0)) - ntl / lev
    if copy is None:
        state.put_copy(Copy(coin, leader, now_ms, lev, actual_cross, es.sizing_mode.value))
        out["opened"].append(coin)
    else:
        # An add never re-leverages or re-records the copy row -- leverage,
        # margin mode and sizing_mode were fixed at open time and are left
        # exactly as they are on the exchange.
        out["added"].append(coin)
    log_event(EngineEvent(ts_ms=now_ms, action=action, leader=leader, coin=coin, side=side,
                           notional_usd=round(ntl, 2), leverage=lev))


def _update_day_pnl(state: EngineState, now_ms: int, equity_usd: float) -> float:
    """PnL since the UTC day's equity anchor. Re-anchors at the first cycle
    of a new UTC day. NOT adjusted for deposits/withdrawals -- see the
    README's "daily_loss_limit_usd" section for why that is a documented
    limitation, not an oversight: a mid-day transfer will be read as PnL."""
    today = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    anchor = state.get_kv("day_anchor")
    if not isinstance(anchor, dict) or anchor.get("day") != today:
        anchor = {"day": today, "equity_usd": equity_usd}
        state.set_kv("day_anchor", anchor)
    return equity_usd - float(anchor["equity_usd"])


def _halt_check(state: EngineState, settings: Settings, day_pnl_usd: float,
                log_event: LogEvent, now_ms: int) -> Optional[str]:
    """`daily_loss_limit_usd` is always <= 0 by the contract; 0 means off.
    Halting blocks `entries_ok` only -- exits never check this."""
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


def _build_positions(state: EngineState, our_account: Dict[str, Any]) -> List[CopyPosition]:
    """Always from the REAL `copies` table, regardless of `dry_run` -- a
    dry-run shadow position is not real and must never be surfaced as a
    `CopyPosition` (see the README's "dry_run" section)."""
    raw_positions = our_account.get("raw_positions") or {}
    positions = our_account.get("positions") or {}
    out: List[CopyPosition] = []
    for c in state.all_copies():
        raw = raw_positions.get(c.coin) or {}
        pos = positions.get(c.coin) or {}
        szi = float(pos.get("szi") or 0.0)
        entry_px = float(pos.get("entry_px") or raw.get("entryPx") or 0.0)
        mark_px = 0.0
        pv = raw.get("positionValue")
        if pv is not None and szi:
            try:
                mark_px = abs(float(pv) / szi)
            except (TypeError, ValueError, ZeroDivisionError):
                mark_px = 0.0
        notional_usd = abs(szi) * (mark_px or entry_px)
        liq_px = raw.get("liquidationPx")
        out.append(CopyPosition(
            coin=c.coin, leader=c.leader, side="long" if szi >= 0 else "short", size=szi,
            entry_px=entry_px, mark_px=mark_px, notional_usd=round(notional_usd, 4),
            leverage=c.leverage, is_cross=c.is_cross,
            unrealized_pnl_usd=float(raw.get("unrealizedPnl") or 0.0),
            liquidation_px=float(liq_px) if liq_px is not None else None,
            opened_ms=c.opened_ms, sizing_mode=SizingMode(c.sizing_mode),
        ))
    return out
