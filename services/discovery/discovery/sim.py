"""Copy-sim: replay one leader's reconstructed position events through the
SAME sizing/leverage/fee/liquidation rules the live engine uses
(`engine.sizing`, confirmed against the real module at
services/engine/engine/sizing.py), and report what COPYING him would have
earned a simulated copier -- not what he earned trading his own account.

── engine.sizing call contract (real signatures, read 2026-10-02) ────────
    exchange_leverage(settings: Settings, his_lev: float, coin_max: int) -> int
    open_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                  our_equity: float, n_leaders: int, exchange_lev: int) -> float
    add_notional(settings: Settings, his_added_ntl: float, his_equity: float,
                 our_equity: float, n_leaders: int, our_current_notional: float,
                 his_frac_added: float) -> float
    worse_entry_ok(side: str, mid: float, entry: float, pct: float) -> bool
        `mid` = our candidate execution price, `entry` = his fill price.
    bump(notional: float, settings: Settings) -> float
        Returns notional UNCHANGED if still under HL_MIN_ORDER_USD and
        either min_order_bump is off or it's under the 25%-of-floor bump
        threshold -- caller must check the result against HL_MIN_ORDER_USD
        and skip if still short.
    liq_distance_pct(leverage: int, is_cross: bool, maint_frac: float) -> float
        `(1/leverage - maint_frac) * 100`. `maint_frac` is NOT ours to
        invent: services/web's liquidation.ts establishes the project's own
        convention, `1 / (2 * coin_max_leverage)` -- HL fixes maintenance
        margin at half the ASSET's max-leverage initial-margin fraction,
        independent of the leverage we actually chose. We use the coin's
        real max leverage (`venue.max_leverage(coin)`), not a guess.

n_leaders is always passed as 1: discovery scores each candidate as "if I
copied JUST this wallet with sim_equity_usd dedicated to it," not diluted
across a multi-leader book. That is the whole point of ranking leaders
individually -- see README.

── sim mechanics (full bias list in README) ────────────────────────────────
- Execution price = the open of the next full 1-minute candle after the
  leader's fill, offset by SLIPPAGE_BPS against us. This is the copy
  latency model: we can't react faster than "next minute," and we cross
  the spread/impact the leader didn't pay.
- A flip (position crosses zero in one fill) becomes two leader events --
  a full close then a full open -- because a copier's book can't flip
  atomically either.
- Positions opened before our fetch window are invisible to us: only opens
  that happen inside the window get copied, which matches what a real
  copier watching from "now" would do.
- Liquidation is checked on every 1-minute candle's adverse wick. A
  liquidation loses exactly the margin behind that one copy and the copy
  is removed; nothing else in the book is affected (isolated semantics,
  applied even when margin_mode=cross -- see liq_distance_pct's own
  docstring: for cross this is a conservative "at least this close" bound,
  not exact, since true cross liquidation draws on the whole account).
- leverage_mode="match" and sizing_mode="proportional" both need the
  leader's state (his per-coin leverage, his equity) that fills alone
  don't carry. Both use a CURRENT snapshot (account_state's per-coin `lev`,
  and the leaderboard row's account_value_usd) for the whole window --
  his historical state at each fill time isn't recoverable. This is the
  task-sanctioned approximation ("his equity for proportional mode comes
  from his current account value") extended consistently to leverage.
- A copy's leverage is fixed for its lifetime once opened (set at the
  "open" event); an "add" reuses it rather than recomputing
  exchange_leverage, matching isolated margin (you can't silently
  re-leverage an open isolated position).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from contracts.models import HL_MIN_ORDER_USD, MarginMode, Settings
from contracts.venue import Venue

from . import candles_cache
from .positions import PositionEvent

TAKER_FEE_RATE = 0.00045          # 0.045%
SLIPPAGE_BPS = 2.0                # our copy latency model's assumed extra slippage vs candle open
CANDLE_INTERVAL = "1m"
N_LEADERS = 1                     # score each candidate as if copied alone, not book-diluted


@dataclass
class _Copy:
    coin: str
    side: str            # "long" | "short"
    notional_usd: float
    margin_usd: float
    leverage: int
    entry_px: float
    opened_ms: int
    last_mark_px: float
    liq_dist_pct: float


@dataclass
class SimResult:
    sim_return_pct: float
    sim_max_drawdown_pct: float
    sim_liquidations: int
    sim_copies: int
    sim_skipped_min_order: int
    sim_fees_usd: float
    flags: List[str] = field(default_factory=list)


def _is_buy_action(kind: str, side: str) -> bool:
    if kind in ("open", "add"):
        return side == "long"
    return side == "short"   # reduce/close: buying back a short, selling a long


def _unrealized_pnl(copy: _Copy, mark_px: float) -> float:
    sign = 1.0 if copy.side == "long" else -1.0
    if copy.entry_px <= 0:
        return 0.0
    return copy.notional_usd * ((mark_px / copy.entry_px) - 1.0) * sign


def _liq_px(entry_px: float, side: str, dist_pct: float) -> float:
    frac = dist_pct / 100.0
    return entry_px * (1.0 - frac) if side == "long" else entry_px * (1.0 + frac)


class _State:
    def __init__(self, sim_equity_usd: float):
        self.cash = sim_equity_usd
        self.open_copies: Dict[str, _Copy] = {}
        self.fees_paid = 0.0
        self.liquidations = 0
        self.opens_done = 0
        self.skipped_min_order = 0
        self.flags: List[str] = []
        self.peak = sim_equity_usd
        self.trough_pct = 0.0
        self.last_mark_ms = 0

    def total_equity(self) -> float:
        return self.cash + sum(_unrealized_pnl(c, c.last_mark_px) for c in self.open_copies.values())

    def mark(self, ts_ms: int) -> None:
        eq = self.total_equity()
        self.last_mark_ms = ts_ms
        if eq > self.peak:
            self.peak = eq
        if self.peak > 0:
            dd = (eq - self.peak) / self.peak * 100.0
            if dd < self.trough_pct:
                self.trough_pct = dd

    def available_margin(self) -> float:
        return self.total_equity() - sum(c.margin_usd for c in self.open_copies.values())


def _candle_dict(conn: sqlite3.Connection, venue: Venue, coin: str, start_ms: int,
                  end_ms: int) -> Dict[int, Dict[str, float]]:
    if end_ms < start_ms:
        return {}
    rows = candles_cache.get_candles(conn, venue, coin, CANDLE_INTERVAL, start_ms, end_ms)
    return {int(r["t_ms"]): r for r in rows}


def _next_minute_open(candles: Dict[int, Dict[str, float]], time_ms: int) -> Optional[float]:
    minute = ((time_ms // 60_000) + 1) * 60_000
    row = candles.get(minute)
    if row is not None:
        return float(row["o"])
    future = sorted(t for t in candles if t >= minute)   # sparse data fallback
    return float(candles[future[0]]["o"]) if future else None


def _walk_candles(state: _State, candles_by_coin: Dict[str, Dict[int, Dict[str, float]]],
                   from_ms: int, to_ms: int) -> None:
    """Advance the mark-to-market clock from from_ms to to_ms, minute by
    minute, checking every currently-open copy for a liquidating wick."""
    if not state.open_copies or to_ms <= from_ms:
        return
    start_minute = ((from_ms // 60_000) + 1) * 60_000
    t = start_minute
    while t <= to_ms:
        for coin in list(state.open_copies.keys()):
            row = candles_by_coin.get(coin, {}).get(t)
            if row is None:
                continue
            copy = state.open_copies[coin]
            liq_px = _liq_px(copy.entry_px, copy.side, copy.liq_dist_pct)
            hit = row["l"] <= liq_px if copy.side == "long" else row["h"] >= liq_px
            if hit:
                state.cash -= copy.margin_usd
                state.liquidations += 1
                state.flags.append(f"liquidated:{coin}")
                del state.open_copies[coin]
                continue
            copy.last_mark_px = float(row["c"])
        state.mark(t)
        t += 60_000


def simulate_wallet(
    conn: sqlite3.Connection,
    venue: Venue,
    events: List[PositionEvent],
    leader_equity_usd: float,
    leader_leverage_by_coin: Dict[str, float],
    settings: Settings,
    sim_equity_usd: float,
    window_start_ms: int,
    window_end_ms: int,
    sizing: Any,
) -> SimResult:
    state = _State(sim_equity_usd)
    state.last_mark_ms = window_start_ms

    coins = sorted({e.coin for e in events})
    # max_leverage() == 0 means "unknown" (contracts/venue.py: never silently fall back to 1 -- a
    # coin we can't size never gets opened at all, see the "open" branch below, rather than being
    # mis-simulated at a fabricated 1x).
    coin_max_lev: Dict[str, int] = {}
    unknown_max_lev: set = set()
    for c in coins:
        v = venue.max_leverage(c)
        if not v or v < 1:
            unknown_max_lev.add(c)
            coin_max_lev[c] = 1
        else:
            coin_max_lev[c] = v
    candles_by_coin: Dict[str, Dict[int, Dict[str, float]]] = {}
    for c in coins:
        first_t = min(e.time_ms for e in events if e.coin == c)
        candles_by_coin[c] = _candle_dict(conn, venue, c, first_t, window_end_ms)

    is_cross = settings.margin_mode == MarginMode.cross

    for event in events:
        _walk_candles(state, candles_by_coin, state.last_mark_ms, event.time_ms)

        exec_px = _next_minute_open(candles_by_coin.get(event.coin, {}), event.time_ms)
        if exec_px is None:
            state.flags.append(f"no_candle_data:{event.coin}")
            continue
        is_buy = _is_buy_action(event.kind, event.side)
        exec_px = exec_px * (1 + SLIPPAGE_BPS / 10_000) if is_buy else exec_px * (1 - SLIPPAGE_BPS / 10_000)

        if event.kind == "open":
            if event.coin in state.open_copies:
                continue  # defensive: already have one open for this coin
            if event.coin in unknown_max_lev:
                state.flags.append(f"max_leverage_unknown:{event.coin}")
                continue
            if len(state.open_copies) >= settings.max_open_copies:
                state.flags.append(f"max_open_copies:{event.coin}")
                continue
            if not sizing.worse_entry_ok(event.side, exec_px, event.px, settings.max_worse_entry_pct):
                state.flags.append(f"worse_entry:{event.coin}")
                continue
            coin_max = coin_max_lev[event.coin]
            his_lev = leader_leverage_by_coin.get(event.coin, float(coin_max))
            lev = sizing.exchange_leverage(settings, his_lev, coin_max)
            leader_notional = event.delta_sz * event.px
            notional = sizing.open_notional(
                settings, leader_notional, leader_equity_usd, state.total_equity(), N_LEADERS, lev,
            )
            notional = sizing.bump(notional, settings)
            if notional < HL_MIN_ORDER_USD:
                state.skipped_min_order += 1
                continue
            margin = notional / lev
            if margin > state.available_margin():
                state.flags.append(f"margin_room:{event.coin}")
                continue
            fee = notional * TAKER_FEE_RATE
            state.cash -= fee
            state.fees_paid += fee
            maint_frac = 1.0 / (2.0 * coin_max)
            liq_dist = sizing.liq_distance_pct(lev, is_cross, maint_frac)
            state.open_copies[event.coin] = _Copy(
                coin=event.coin, side=event.side, notional_usd=notional, margin_usd=margin,
                leverage=lev, entry_px=exec_px, opened_ms=event.time_ms, last_mark_px=exec_px,
                liq_dist_pct=liq_dist,
            )
            state.opens_done += 1

        elif event.kind == "add":
            copy = state.open_copies.get(event.coin)
            if copy is None:
                continue  # position pre-dated our window; nothing to add to
            if not sizing.worse_entry_ok(event.side, exec_px, event.px, settings.max_worse_entry_pct):
                state.flags.append(f"worse_entry:{event.coin}")
                continue
            leader_notional = event.delta_sz * event.px
            his_frac_added = event.delta_sz / abs(event.start_position) if event.start_position else 0.0
            add_notional = sizing.add_notional(
                settings, leader_notional, leader_equity_usd, state.total_equity(), N_LEADERS,
                copy.notional_usd, his_frac_added,
            )
            add_notional = sizing.bump(add_notional, settings)
            if add_notional < HL_MIN_ORDER_USD:
                state.skipped_min_order += 1
                continue
            add_margin = add_notional / copy.leverage
            if add_margin > state.available_margin():
                state.flags.append(f"margin_room:{event.coin}")
                continue
            fee = add_notional * TAKER_FEE_RATE
            state.cash -= fee
            state.fees_paid += fee
            new_notional = copy.notional_usd + add_notional
            copy.entry_px = (copy.entry_px * copy.notional_usd + exec_px * add_notional) / new_notional
            copy.notional_usd = new_notional
            copy.margin_usd += add_margin

        elif event.kind in ("reduce", "close"):
            copy = state.open_copies.get(event.coin)
            if copy is None:
                continue  # position pre-dated our window; nothing to reduce/close
            if event.kind == "close" or event.end_position == 0:
                reduce_notional = copy.notional_usd
            else:
                frac = event.delta_sz / abs(event.start_position) if event.start_position else 1.0
                raw = copy.notional_usd * frac
                bumped = sizing.bump(raw, settings)
                if bumped < HL_MIN_ORDER_USD:
                    state.skipped_min_order += 1
                    continue
                reduce_notional = min(bumped, copy.notional_usd)
            pnl = reduce_notional * ((exec_px / copy.entry_px) - 1.0) * (1.0 if copy.side == "long" else -1.0)
            fee = reduce_notional * TAKER_FEE_RATE
            state.cash += pnl - fee
            state.fees_paid += fee
            remaining = copy.notional_usd - reduce_notional
            if remaining <= 1e-9 or event.kind == "close":
                del state.open_copies[event.coin]
            else:
                margin_frac = reduce_notional / copy.notional_usd
                copy.margin_usd -= copy.margin_usd * margin_frac
                copy.notional_usd = remaining

        state.mark(event.time_ms)

    # fast-forward any still-open copies to the window end for final MTM + liquidation
    _walk_candles(state, candles_by_coin, state.last_mark_ms, window_end_ms)
    state.mark(window_end_ms)

    final_equity = state.total_equity()
    sim_return_pct = (final_equity / sim_equity_usd - 1.0) * 100.0 if sim_equity_usd > 0 else 0.0

    return SimResult(
        sim_return_pct=sim_return_pct,
        sim_max_drawdown_pct=state.trough_pct,
        sim_liquidations=state.liquidations,
        sim_copies=state.opens_done,
        sim_skipped_min_order=state.skipped_min_order,
        sim_fees_usd=state.fees_paid,
        flags=state.flags,
    )
