"""Copy-sim: replay one leader's reconstructed position events through the
SAME sizing/leverage rules the live engine uses (`engine.sizing`, imported,
not re-implemented) and report what COPYING him would have earned a
simulated copier, not what he earned on his own account.

Pure: no I/O. The runner hands in pre-built price series
(candles_cache.Series, mixed 1m/15m/1h by age) and per-coin max leverage.

── engine.sizing calls ─────────────────────────────────────────────────────
    exchange_leverage(settings, his_lev, coin_max) -> int
    open_notional(settings, his_added_ntl, his_equity, our_equity, n_leaders, lev) -> float
    add_notional(settings, his_added_ntl, his_equity, our_equity, n_leaders,
                 our_current_notional, his_frac_added) -> float
    worse_entry_ok(side, mid, entry, pct) -> bool
    bump(notional, settings) -> float      (caller skips if still < HL_MIN_ORDER_USD)
    liq_distance_pct(leverage, is_cross, maint_frac) -> float
maint_frac = 1 / (2 * coin_max_leverage), HL's maintenance margin rule.
n_leaders = 1: each candidate is scored as if copied alone.

── model (full bias list in README) ────────────────────────────────────────
- Leader events come from fills coalesced per engine poll interval
  (positions.coalesce_by_poll): the engine sees one net delta per poll.
- Execution price: the open of the 1m bar right after his fill, plus
  SLIPPAGE_BPS against us, when a 1m bar exists there (last ~3.4 days).
  Older than that HL has no 1m bars, so his own fill price plus
  FALLBACK_SLIPPAGE_BPS against us (latency + spread estimate).
- Mark-to-market and liquidation run bar by bar in end-time order across
  coins, on whatever resolution the series has at that age. A bar is
  checked for a copy only if it STARTS at or after the copy opened, and
  only once it has fully ENDED before the next leader event: the partial
  bars at entry and exit are unchecked (up to 1 bar each; 2 min at 1m,
  30 min at 15m).
- Liquidation: an adverse wick through entry*(1 -/+ liq_distance) loses
  exactly that copy's posted margin (isolated semantics, also used for
  cross as a lower bound). A bar that gaps past the liquidation price
  without a wick in our data (missing bars) still caps the loss at the
  margin: unrealized PnL of an isolated copy is floored at -margin.
- A copy's leverage is fixed at open; adds reuse it.
- Contract v8, from the effective settings, as the engine applies them:
  trade_direction counter takes the opposite side of every position he opens
  (sizes unchanged; execution price, worse-entry check, liquidation price and
  PnL all on OUR inverted side; his reduces/closes still close ours). Coin
  allow/block lists skip opens/adds (flag "filtered:<coin>", via
  engine.sizing.coin_allowed); exits are never filtered. `paused` is ignored:
  the sim projects the terms, not the wallet's current on/off state.
"""
from __future__ import annotations

import heapq
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from contracts.models import HL_MIN_ORDER_USD, MarginMode, Settings, SizingMode, SmallAccountMode

from .candles_cache import Series
from .positions import PositionEvent

TAKER_FEE_RATE = 0.00045          # 0.045%
SLIPPAGE_BPS = 2.0                # on top of the next 1m open
FALLBACK_SLIPPAGE_BPS = 5.0       # on top of his fill price when no 1m bar exists
N_LEADERS = 1
MARGIN_ROOM_FRAC = 0.95           # engine: room = available x lev x 0.95 (core._execute_entry)
FIXED_CAP_SLACK = 1.02            # fixed modes: a copy may run 2% over its fixed size (rounding)
FIXED_MODES = (SizingMode.fixed_margin, SizingMode.fixed_notional)

Trace = Optional[Callable[[str], None]]


@dataclass
class _Copy:
    coin: str
    side: str
    notional_usd: float
    margin_usd: float
    leverage: int
    entry_px: float
    opened_ms: int
    last_mark_px: float
    liq_px: float
    next_bar: int          # index into the coin's Series of the next unchecked bar
    cap_margin: float = 0.0   # fixed modes: most margin this copy may ever hold


@dataclass
class SimResult:
    sim_return_pct: float
    sim_max_drawdown_pct: float
    sim_liquidations: int
    sim_copies: int
    sim_skipped_min_order: int
    sim_fees_usd: float
    flags: List[str] = field(default_factory=list)
    open_copies_at_end: int = 0
    curve: List[tuple] = field(default_factory=list)   # [(t_ms, equity)] when curve_step_ms is set


def _is_buy_action(kind: str, side: str) -> bool:
    """`side` is OUR copy's side (his side, inverted for counter)."""
    if kind in ("open", "add"):
        return side == "long"
    return side == "short"


def _flip(side: str) -> str:
    return "short" if side == "long" else "long"


def _upnl(copy: _Copy, mark_px: float) -> float:
    if copy.entry_px <= 0:
        return 0.0
    sign = 1.0 if copy.side == "long" else -1.0
    # isolated: a copy can never lose more than its posted margin
    return max(-copy.margin_usd, copy.notional_usd * (mark_px / copy.entry_px - 1.0) * sign)


def _liq_px(entry_px: float, side: str, dist_pct: float) -> float:
    frac = dist_pct / 100.0
    return entry_px * (1.0 - frac) if side == "long" else entry_px * (1.0 + frac)


class _State:
    def __init__(self, equity: float, trace: Trace):
        self.cash = equity
        self.open: Dict[str, _Copy] = {}
        self.fees = 0.0
        self.liqs = 0
        self.opens = 0
        self.skipped_min = 0
        self.flags: List[str] = []
        self.peak = equity
        self.trough_pct = 0.0
        self.trace = trace
        self.curve: List[tuple] = []
        self.curve_step = 0
        self.next_curve_t = 0

    def curve_to(self, t_ms: int) -> None:
        """Record equity at every curve boundary <= t_ms not recorded yet,
        before anything at t_ms is applied."""
        if self.curve_step <= 0:
            return
        while self.next_curve_t <= t_ms:
            self.curve.append((self.next_curve_t, round(self.equity(), 6)))
            self.next_curve_t += self.curve_step

    def equity(self) -> float:
        return self.cash + sum(_upnl(c, c.last_mark_px) for c in self.open.values())

    def mark(self) -> None:
        eq = self.equity()
        if eq > self.peak:
            self.peak = eq
        if self.peak > 0:
            self.trough_pct = min(self.trough_pct, (eq - self.peak) / self.peak * 100.0)

    def available_margin(self, is_cross: bool) -> float:
        """Isolated: only cash not already posted as margin can back a new
        order; an open copy's unrealized gain is locked inside it. Cross:
        unrealized PnL counts. (Regression: counting isolated unrealized
        gains let one copy's adds post more margin than the account had.)"""
        posted = sum(c.margin_usd for c in self.open.values())
        return (self.equity() if is_cross else self.cash) - posted

    def liquidate(self, copy: _Copy, t_ms: int, why: str) -> None:
        self.cash -= copy.margin_usd
        self.liqs += 1
        self.flags.append(f"liquidated:{copy.coin}")
        del self.open[copy.coin]
        if self.trace:
            self.trace(f"  {t_ms} LIQ   {copy.coin} {copy.side} ntl=${copy.notional_usd:.2f} "
                       f"lev={copy.leverage}x entry={copy.entry_px:.6g} liq={copy.liq_px:.6g} "
                       f"loss=${copy.margin_usd:.2f} ({why})")


def _advance(state: _State, series: Dict[str, Series], to_ms: int) -> None:
    """Process, in end-time order across coins, every bar that ended by
    to_ms for every open copy."""
    heap: List[tuple] = []
    for coin, cp in state.open.items():
        s = series.get(coin)
        if s is not None and cp.next_bar < len(s) and s.end[cp.next_bar] <= to_ms:
            heapq.heappush(heap, (s.end[cp.next_bar], coin))
    while heap:
        end, coin = heapq.heappop(heap)
        state.curve_to(end - 1)
        cp = state.open.get(coin)
        if cp is None:
            continue
        s = series[coin]
        i = cp.next_bar
        cp.next_bar += 1
        hit = s.l[i] <= cp.liq_px if cp.side == "long" else s.h[i] >= cp.liq_px
        if hit:
            state.liquidate(cp, end, f"{s.step[i] // 60_000}m wick")
        else:
            cp.last_mark_px = s.c[i]
            if _upnl(cp, s.c[i]) <= -cp.margin_usd:
                state.liquidate(cp, end, "gap past liq price")
        state.mark()
        if coin in state.open and cp.next_bar < len(s) and s.end[cp.next_bar] <= to_ms:
            heapq.heappush(heap, (s.end[cp.next_bar], coin))


def _exec_price(s: Optional[Series], e: PositionEvent, is_buy: bool) -> float:
    if s is not None and len(s):
        minute = (e.time_ms // 60_000 + 1) * 60_000
        i = bisect_left(s.t, minute)
        if i < len(s) and s.t[i] == minute and s.step[i] == 60_000:
            px = s.o[i]
            return px * (1 + SLIPPAGE_BPS / 1e4) if is_buy else px * (1 - SLIPPAGE_BPS / 1e4)
    px = e.px
    return px * (1 + FALLBACK_SLIPPAGE_BPS / 1e4) if is_buy else px * (1 - FALLBACK_SLIPPAGE_BPS / 1e4)


def _update_his_book(book: Dict[str, Dict[str, float]], e: PositionEvent) -> None:
    """His live book as the engine would read it after this event: signed
    size and his AVERAGE entry (engine.sizing.his_notional sizes off entry,
    not mark). A position from before the window enters at this event's px."""
    if e.end_position == 0:
        book.pop(e.coin, None)
        return
    cur = book.get(e.coin)
    if e.kind == "open" or cur is None:
        book[e.coin] = {"szi": e.end_position, "entry_px": e.px}
    elif e.kind == "add":
        prev = abs(cur["szi"])
        cur["entry_px"] = (prev * cur["entry_px"] + e.delta_sz * e.px) / abs(e.end_position)
        cur["szi"] = e.end_position
    else:
        cur["szi"] = e.end_position


def simulate_wallet(
    events: List[PositionEvent],
    series: Dict[str, Series],
    coin_max_lev: Dict[str, int],
    leader_equity_usd: float,
    leader_leverage_by_coin: Dict[str, float],
    settings: Settings,
    sim_equity_usd: float,
    window_end_ms: int,
    sizing: Any,
    trace: Trace = None,
    curve_step_ms: Optional[int] = None,
    window_start_ms: Optional[int] = None,
) -> SimResult:
    """events: chronological, every coin. coin_max_lev: 0/absent = unknown
    (the coin is never opened rather than sized at a made-up 1x).

    curve_step_ms: also return SimResult.curve, the copier's marked equity
    at every multiple of the step from window_start_ms (default: the first
    event, floored to the step) to window_end_ms, plus the final point.

    Entry sizing mirrors engine.core._execute_entry: raw notional from
    engine.sizing, trimmed to margin room (available x lev x 0.95), to the
    allocation cap (allocation mode), bumped, then skipped if still under
    the minimum. On top of that, in the FIXED modes a copy never grows past
    its fixed size: total copy margin <= max(fixed margin, margin posted at
    open) x 1.02 (fixed_notional: the same on notional). Without it,
    `add_notional`'s "scale by his fractional add" plus the $10.50 bump on
    every tiny add grew a $1-margin copy to most of the account (0x30afce2f
    on xyz:DRAM: $1 -> $126 margin; 0xbf732ea0: -99.96% from 2 liqs).
    """
    st = _State(sim_equity_usd, trace)
    is_cross = settings.margin_mode == MarginMode.cross
    fixed_mode = settings.sizing_mode in FIXED_MODES
    allocation = settings.sizing_mode == SizingMode.allocation
    his_book: Dict[str, Dict[str, float]] = {}   # his positions as the engine reads them (in-window events)
    concentrate = allocation and settings.small_account_mode == SmallAccountMode.concentrate
    counter = getattr(settings.trade_direction, "value", settings.trade_direction) == "counter"
    if curve_step_ms and curve_step_ms > 0:
        start = window_start_ms if window_start_ms is not None else (events[0].time_ms if events else window_end_ms)
        st.curve_step = int(curve_step_ms)
        st.next_curve_t = (start // st.curve_step) * st.curve_step

    def room_ntl(lev: int) -> float:
        free = st.available_margin(is_cross)
        return max(0.0, free) * lev * MARGIN_ROOM_FRAC

    def alloc_room(lev: int) -> float:
        used = sum(c.margin_usd for c in st.open.values())
        return sizing.allocation_room_ntl(settings, used, lev)

    for e in events:
        _advance(st, series, e.time_ms)
        st.curve_to(e.time_ms)
        s = series.get(e.coin)
        held = st.open.get(e.coin)
        # our side: an open copy keeps its own; a fresh open is his side (copy)
        # or the opposite (counter)
        our_side = held.side if held is not None else (_flip(e.side) if counter else e.side)
        is_buy = _is_buy_action(e.kind, our_side)
        px = _exec_price(s, e, is_buy)
        _update_his_book(his_book, e)
        if e.kind in ("open", "add") and not sizing.coin_allowed(settings, e.coin):
            st.flags.append(f"filtered:{e.coin}")
            continue
        his_gross = sizing.gross_notional(his_book)
        his_entry = his_book.get(e.coin, {}).get("entry_px", e.px)
        his_added = e.delta_sz * his_entry          # engine: (|cur| - |prev|) x his entry_px
        scale = 1.0
        if concentrate and e.kind in ("open", "add"):
            levs = {c: max(1, sizing.exchange_leverage(settings, leader_leverage_by_coin.get(c, 1.0),
                                                       int(coin_max_lev.get(c) or 1)))
                    for c in his_book}
            ntl_book = {c: sizing.his_notional(p) for c, p in his_book.items()}
            base = sizing.base_slices(ntl_book, leader_equity_usd, settings.allocation_usd,
                                      settings.exposure_mode, levs)
            eligible, scale = sizing.concentrate(base, ntl_book, held=set(st.open))
            if e.coin not in eligible:
                st.flags.append(f"concentrate_skip:{e.coin}")
                continue

        if e.kind == "open":
            if e.coin in st.open:
                continue
            coin_max = int(coin_max_lev.get(e.coin) or 0)
            if coin_max < 1:
                st.flags.append(f"max_leverage_unknown:{e.coin}")
                continue
            if len(st.open) >= settings.max_open_copies:
                st.flags.append(f"max_open_copies:{e.coin}")
                continue
            if not sizing.worse_entry_ok(our_side, px, e.px, settings.max_worse_entry_pct):
                st.flags.append(f"worse_entry:{e.coin}")
                continue
            lev = sizing.exchange_leverage(settings, leader_leverage_by_coin.get(e.coin, float(coin_max)), coin_max)
            raw = sizing.open_notional(settings, his_added, leader_equity_usd, st.equity(), N_LEADERS,
                                       lev, his_gross) * scale
            ntl = min(raw, room_ntl(lev))
            if allocation:
                ntl = min(ntl, alloc_room(lev))
            ntl = sizing.bump(ntl, settings)
            if ntl < HL_MIN_ORDER_USD:
                if raw >= HL_MIN_ORDER_USD or sizing.bump(raw, settings) >= HL_MIN_ORDER_USD:
                    st.flags.append(f"margin_room:{e.coin}")
                else:
                    st.skipped_min += 1
                continue
            margin = ntl / lev
            if margin > st.available_margin(is_cross) + 1e-9:
                st.flags.append(f"margin_room:{e.coin}")
                continue
            fee = ntl * TAKER_FEE_RATE
            st.cash -= fee
            st.fees += fee
            dist = sizing.liq_distance_pct(lev, is_cross, 1.0 / (2.0 * coin_max))
            nb = bisect_left(s.t, e.time_ms) if s is not None else 0
            fixed_margin = (settings.fixed_margin_usd if settings.sizing_mode == SizingMode.fixed_margin
                            else settings.fixed_notional_usd / lev)
            st.open[e.coin] = _Copy(e.coin, our_side, ntl, margin, lev, px, e.time_ms, px,
                                    _liq_px(px, our_side, dist), nb,
                                    cap_margin=max(fixed_margin, margin) * FIXED_CAP_SLACK if fixed_mode else 0.0)
            st.opens += 1
            if trace:
                trace(f"  {e.time_ms} OPEN  {e.coin} {our_side} ntl=${ntl:.2f} margin=${margin:.2f} "
                      f"lev={lev}x px={px:.6g} his_px={e.px:.6g} liq={st.open[e.coin].liq_px:.6g}")

        elif e.kind == "add":
            cp = st.open.get(e.coin)
            if cp is None:
                continue
            if not sizing.worse_entry_ok(cp.side, px, e.px, settings.max_worse_entry_pct):
                st.flags.append(f"worse_entry:{e.coin}")
                continue
            frac = e.delta_sz / abs(e.start_position) if e.start_position else 0.0
            if fixed_mode and frac <= 0:
                continue    # engine: nothing to scale by
            our_ntl_now = cp.notional_usd * px / cp.entry_px if cp.entry_px > 0 else cp.notional_usd
            raw = sizing.add_notional(settings, his_added, leader_equity_usd, st.equity(), N_LEADERS,
                                      our_ntl_now, frac, his_gross, cp.leverage) * scale
            add = min(raw, room_ntl(cp.leverage))
            if allocation:
                add = min(add, alloc_room(cp.leverage))
            cap_room = None
            if fixed_mode:
                cap_room = max(0.0, cp.cap_margin - cp.margin_usd) * cp.leverage
                add = min(add, cap_room)
            add = sizing.bump(add, settings)
            if cap_room is not None and add > cap_room + 1e-9:
                st.flags.append(f"add_capped:{e.coin}")
                continue
            if add < HL_MIN_ORDER_USD:
                if cap_room is not None and cap_room < HL_MIN_ORDER_USD and raw >= cap_room:
                    st.flags.append(f"add_capped:{e.coin}")
                else:
                    st.skipped_min += 1
                continue
            add_margin = add / cp.leverage
            if add_margin > st.available_margin(is_cross) + 1e-9:
                st.flags.append(f"margin_room:{e.coin}")
                continue
            fee = add * TAKER_FEE_RATE
            st.cash -= fee
            st.fees += fee
            new_ntl = cp.notional_usd + add
            cp.entry_px = (cp.entry_px * cp.notional_usd + px * add) / new_ntl
            cp.notional_usd = new_ntl
            cp.margin_usd += add_margin
            dist = sizing.liq_distance_pct(cp.leverage, is_cross, 1.0 / (2.0 * int(coin_max_lev[e.coin])))
            cp.liq_px = _liq_px(cp.entry_px, cp.side, dist)
            if trace:
                trace(f"  {e.time_ms} ADD   {e.coin} +${add:.2f} (his +{frac * 100:.0f}%) -> ntl=${new_ntl:.2f} "
                      f"margin=${cp.margin_usd:.2f}")

        else:   # reduce / close
            cp = st.open.get(e.coin)
            if cp is None:
                continue
            if e.kind == "close" or e.end_position == 0:
                red = cp.notional_usd
            else:
                frac = e.delta_sz / abs(e.start_position) if e.start_position else 1.0
                bumped = sizing.bump(cp.notional_usd * frac, settings)
                if bumped < HL_MIN_ORDER_USD:
                    st.skipped_min += 1
                    continue
                red = min(bumped, cp.notional_usd)
            share = red / cp.notional_usd
            sign = 1.0 if cp.side == "long" else -1.0
            pnl = max(-cp.margin_usd * share, red * (px / cp.entry_px - 1.0) * sign)
            fee = red * TAKER_FEE_RATE
            st.cash += pnl - fee
            st.fees += fee
            if trace:
                trace(f"  {e.time_ms} {e.kind.upper():5s} {e.coin} ${red:.2f} px={px:.6g} pnl=${pnl:.2f}")
            if share >= 1.0 - 1e-9:
                del st.open[e.coin]
            else:
                cp.margin_usd *= (1.0 - share)
                cp.notional_usd -= red

        st.mark()

    _advance(st, series, window_end_ms)
    st.curve_to(window_end_ms)
    st.mark()
    final = st.equity()
    if st.curve_step and (not st.curve or st.curve[-1][0] != window_end_ms):
        st.curve.append((window_end_ms, round(final, 6)))
    ret = (final / sim_equity_usd - 1.0) * 100.0 if sim_equity_usd > 0 else 0.0
    if trace:
        trace(f"  end equity=${final:.2f} ret={ret:.2f}% dd={st.trough_pct:.2f}% copies={st.opens} "
              f"liqs={st.liqs} fees=${st.fees:.2f} still_open={len(st.open)}")
    return SimResult(ret, st.trough_pct, st.liqs, st.opens, st.skipped_min, st.fees, st.flags, len(st.open),
                     st.curve)
