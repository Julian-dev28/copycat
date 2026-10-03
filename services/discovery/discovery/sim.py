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
"""
from __future__ import annotations

import heapq
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from contracts.models import HL_MIN_ORDER_USD, MarginMode, Settings

from .candles_cache import Series
from .positions import PositionEvent

TAKER_FEE_RATE = 0.00045          # 0.045%
SLIPPAGE_BPS = 2.0                # on top of the next 1m open
FALLBACK_SLIPPAGE_BPS = 5.0       # on top of his fill price when no 1m bar exists
N_LEADERS = 1

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


def _is_buy_action(kind: str, side: str) -> bool:
    if kind in ("open", "add"):
        return side == "long"
    return side == "short"


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
) -> SimResult:
    """events: chronological, every coin. coin_max_lev: 0/absent = unknown
    (the coin is never opened rather than sized at a made-up 1x)."""
    st = _State(sim_equity_usd, trace)
    is_cross = settings.margin_mode == MarginMode.cross

    for e in events:
        _advance(st, series, e.time_ms)
        s = series.get(e.coin)
        is_buy = _is_buy_action(e.kind, e.side)
        px = _exec_price(s, e, is_buy)

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
            if not sizing.worse_entry_ok(e.side, px, e.px, settings.max_worse_entry_pct):
                st.flags.append(f"worse_entry:{e.coin}")
                continue
            lev = sizing.exchange_leverage(settings, leader_leverage_by_coin.get(e.coin, float(coin_max)), coin_max)
            ntl = sizing.bump(sizing.open_notional(settings, e.delta_sz * e.px, leader_equity_usd,
                                                   st.equity(), N_LEADERS, lev), settings)
            if ntl < HL_MIN_ORDER_USD:
                st.skipped_min += 1
                continue
            margin = ntl / lev
            if margin > st.available_margin(is_cross):
                st.flags.append(f"margin_room:{e.coin}")
                continue
            fee = ntl * TAKER_FEE_RATE
            st.cash -= fee
            st.fees += fee
            dist = sizing.liq_distance_pct(lev, is_cross, 1.0 / (2.0 * coin_max))
            nb = bisect_left(s.t, e.time_ms) if s is not None else 0
            st.open[e.coin] = _Copy(e.coin, e.side, ntl, margin, lev, px, e.time_ms, px,
                                    _liq_px(px, e.side, dist), nb)
            st.opens += 1
            if trace:
                trace(f"  {e.time_ms} OPEN  {e.coin} {e.side} ntl=${ntl:.2f} margin=${margin:.2f} "
                      f"lev={lev}x px={px:.6g} his_px={e.px:.6g} liq={st.open[e.coin].liq_px:.6g}")

        elif e.kind == "add":
            cp = st.open.get(e.coin)
            if cp is None:
                continue
            if not sizing.worse_entry_ok(e.side, px, e.px, settings.max_worse_entry_pct):
                st.flags.append(f"worse_entry:{e.coin}")
                continue
            frac = e.delta_sz / abs(e.start_position) if e.start_position else 0.0
            add = sizing.bump(sizing.add_notional(settings, e.delta_sz * e.px, leader_equity_usd, st.equity(),
                                                  N_LEADERS, cp.notional_usd, frac), settings)
            if add < HL_MIN_ORDER_USD:
                st.skipped_min += 1
                continue
            add_margin = add / cp.leverage
            if add_margin > st.available_margin(is_cross):
                st.flags.append(f"margin_room:{e.coin}")
                continue
            fee = add * TAKER_FEE_RATE
            st.cash -= fee
            st.fees += fee
            new_ntl = cp.notional_usd + add
            cp.entry_px = (cp.entry_px * cp.notional_usd + px * add) / new_ntl
            cp.notional_usd = new_ntl
            cp.margin_usd += add_margin
            # same leverage, new average entry: the liquidation price moves with it
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
    st.mark()
    final = st.equity()
    ret = (final / sim_equity_usd - 1.0) * 100.0 if sim_equity_usd > 0 else 0.0
    if trace:
        trace(f"  end equity=${final:.2f} ret={ret:.2f}% dd={st.trough_pct:.2f}% copies={st.opens} "
              f"liqs={st.liqs} fees=${st.fees:.2f} still_open={len(st.open)}")
    return SimResult(ret, st.trough_pct, st.liqs, st.opens, st.skipped_min, st.fees, st.flags, len(st.open))
