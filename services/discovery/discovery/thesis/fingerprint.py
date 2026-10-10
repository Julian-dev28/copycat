"""The pure core: fills + 1h bars + account value history in, a
StrategyFingerprint out. No I/O, no clock (now_ms is an argument), no AI.
Same input, same fingerprint, byte for byte (see test_thesis_template).

Formulas and thresholds: README.md in this directory and config.py.
"""
from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from contracts.models import CoinStat, EntryContext, StrategyFingerprint, TradeExample, TradingStyle

from .. import positions
from . import config as C
from .indicators import Bars, entry_context, hour_utc, weekday
from .trips import Trip, build_trips

Point = Tuple[int, float]


def _r(x: Optional[float], nd: int = 2) -> Optional[float]:
    if x is None or not math.isfinite(x):
        return None
    return round(x, nd)


def _pct(n: int, d: int) -> Optional[float]:
    return _r(n / d * 100.0) if d > 0 else None


def classify_style(opens_per_day: float, median_hold_h: Optional[float], trips: int) -> Optional[TradingStyle]:
    """Scout's style rule (spec #20), imported so the board and the
    fingerprint never disagree on a trader's style."""
    from ..scout.metrics import classify_style as scout_classify
    return scout_classify(opens_per_day, median_hold_h, trips)


# ── small pure helpers (each has a gate test) ─────────────────────────────

def p90(values: Sequence[float]) -> Optional[float]:
    """Nearest-rank 90th percentile: sorted[ceil(0.9 n) - 1]."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(0.9 * len(s)) - 1)]


def best_session(hour_hist: Sequence[int], hours: int = C.SESSION_HOURS) -> Tuple[int, Optional[float]]:
    """(start hour, share %) of the `hours`-wide UTC window (wrapping
    midnight) holding the most entries. Ties go to the earliest start."""
    total = sum(hour_hist)
    if total == 0 or len(hour_hist) != 24:
        return 0, None
    best_s, best_n = 0, -1
    for s in range(24):
        n = sum(hour_hist[(s + k) % 24] for k in range(hours))
        if n > best_n:
            best_s, best_n = s, n
    return best_s, _r(best_n / total * 100.0)


def equity_at(points: Sequence[Point], t_ms: int) -> Optional[float]:
    """Account value at t: the last positive point at or before t, else the
    first positive point after it. None without any positive point."""
    pts = [(t, v) for t, v in points if v > 0]
    if not pts:
        return None
    ts = [t for t, _ in pts]
    i = bisect.bisect_right(ts, t_ms) - 1
    return pts[i][1] if i >= 0 else pts[0][1]


def fills_truncated(fills: Sequence[Dict[str, Any]], window_start_ms: int) -> bool:
    if len(fills) < C.TRUNCATED_MIN_FILLS:
        return False
    return min(int(f["time_ms"]) for f in fills) > window_start_ms + C.DAY_MS


def coin_stats(fills: Sequence[Dict[str, Any]], trips: Sequence[Trip]) -> List[CoinStat]:
    """Per perp coin over the window's fills: volume sum(px*sz), realized
    PnL sum(closed_pnl - fee), closed trips. Ranked by volume desc, coin name
    breaks ties."""
    perp, _ = positions.split_perp(list(fills))
    agg: Dict[str, List[float]] = {}
    for f in perp:
        a = agg.setdefault(f["coin"], [0.0, 0.0])
        a[0] += abs(float(f["px"]) * float(f["sz"]))
        a[1] += float(f.get("closed_pnl", 0.0)) - float(f.get("fee", 0.0))
    n: Dict[str, int] = {}
    for t in trips:
        n[t.coin] = n.get(t.coin, 0) + 1
    out = [CoinStat(coin=c, volume_usd=round(v, 2), pnl_usd=round(p, 2), trips=n.get(c, 0))
           for c, (v, p) in agg.items()]
    out.sort(key=lambda s: (-s.volume_usd, s.coin))
    return out


def top_profit_coin(stats: Sequence[CoinStat]) -> Tuple[Optional[str], Optional[float]]:
    """(coin, share %) of positive realized PnL earned by the most profitable
    coin. None when no coin made money."""
    pos = [s for s in stats if s.pnl_usd > 0]
    if not pos:
        return None, None
    best = sorted(pos, key=lambda s: (-s.pnl_usd, s.coin))[0]
    return best.coin, _r(best.pnl_usd / sum(s.pnl_usd for s in pos) * 100.0)


# ── tags ──────────────────────────────────────────────────────────────────

_OPS: Dict[str, Callable[[float, float], bool]] = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
}


def assign_tags(metrics: Dict[str, Optional[float]], trips: int, context_n: int) -> List[str]:
    """Apply config.TAG_RULES in order. No tags under MIN_TRIPS_FOR_TAGS
    trips; candle-based tags also need MIN_CONTEXT_FOR_ENTRY_TAGS trips with
    candle context. A None metric never matches."""
    if trips < C.MIN_TRIPS_FOR_TAGS:
        return []
    out: List[str] = []
    for tag, key, op, thr in C.TAG_RULES:
        v = metrics.get(key)
        if v is None:
            continue
        if key in C.CANDLE_METRICS and context_n < C.MIN_CONTEXT_FOR_ENTRY_TAGS:
            continue
        if _OPS[op](v, thr) and tag not in out:
            out.append(tag)
    return out


# ── examples ──────────────────────────────────────────────────────────────

@dataclass
class TripView:
    """A trip plus everything derived for it: context and leverage."""
    trip: Trip
    ctx: EntryContext
    leverage: Optional[float] = None
    pct_of_equity: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def _typical(cands: Sequence[TripView]) -> Optional[TripView]:
    """The candidate closest to the set's median return, then median hold,
    then earliest open, then coin name. Deterministic."""
    if not cands:
        return None
    mr = statistics.median(v.trip.return_pct for v in cands)
    mh = statistics.median(v.trip.hold_h for v in cands)
    return min(cands, key=lambda v: (abs(v.trip.return_pct - mr), abs(v.trip.hold_h - mh),
                                     v.trip.opened_ms, v.trip.coin))


def _in_session(v: TripView, start: int) -> bool:
    return (v.ctx.hour_utc - start) % 24 < C.SESSION_HOURS


# tag -> (predicate on a TripView, why_shown). Order follows the fingerprint's tags.
_TAG_EXAMPLES: Dict[str, Tuple[Callable[[TripView, Dict[str, Any]], bool], str]] = {
    "trend follower": (lambda v, _: v.ctx.trend_aligned is True, "typical trend-aligned entry"),
    "counter-trend": (lambda v, _: v.ctx.trend_aligned is False, "typical counter-trend entry"),
    "dip buyer": (lambda v, _: v.ctx.pullback is True, "typical pullback entry"),
    "breakout buyer": (lambda v, _: v.ctx.breakout is True, "typical breakout entry"),
    "scales in": (lambda v, _: v.trip.adds >= 1, "typical scale-in"),
    "scales out": (lambda v, _: v.trip.exits >= 2, "typical scale-out"),
    "runs winners": (lambda v, _: v.trip.net_pnl_usd > 0, "typical winner"),
    "cuts losers fast": (lambda v, _: v.trip.net_pnl_usd < 0, "typical loser, cut early"),
    "holds losers": (lambda v, _: v.trip.net_pnl_usd < 0, "typical loser, held long"),
    "session trader": (lambda v, s: _in_session(v, s["session_start"]), "typical in-session entry"),
}


def select_examples(views: Sequence[TripView], tags: Sequence[str], session_start: int) -> List[TradeExample]:
    """Fixed rules, in order, skipping a trip already shown, up to
    MAX_EXAMPLES: largest win, largest loss, the typical trip for each tag
    that has a trip predicate (in tag order), the typical trip overall,
    highest leverage, longest hold, most adds, best and worst return on
    notional, then the most recent trips until full."""
    chosen: List[Tuple[TripView, str]] = []
    seen = set()

    def add(v: Optional[TripView], why: str) -> None:
        if v is None or v.trip.key in seen or len(chosen) >= C.MAX_EXAMPLES:
            return
        seen.add(v.trip.key)
        chosen.append((v, why))

    if not views:
        return []
    order = lambda v: (v.trip.opened_ms, v.trip.coin)   # noqa: E731  tie-break: earliest first
    wins = [v for v in views if v.trip.net_pnl_usd > 0]
    losses = [v for v in views if v.trip.net_pnl_usd < 0]
    if wins:
        add(min(wins, key=lambda v: (-v.trip.net_pnl_usd, *order(v))), "largest win")
    if losses:
        add(min(losses, key=lambda v: (v.trip.net_pnl_usd, *order(v))), "largest loss")
    state = {"session_start": session_start}
    for tag in tags:
        rule = _TAG_EXAMPLES.get(tag)
        if rule is None:
            continue
        pred, why = rule
        add(_typical([v for v in views if pred(v, state) and v.trip.key not in seen]), f"{why} ({tag})")
    add(_typical([v for v in views if v.trip.key not in seen]), "most typical trip")
    lev = [v for v in views if v.leverage is not None]
    if lev:
        add(min(lev, key=lambda v: (-(v.leverage or 0.0), *order(v))), "highest leverage")
    add(min(views, key=lambda v: (-v.trip.hold_h, *order(v))), "longest hold")
    adders = [v for v in views if v.trip.adds > 0]
    if adders:
        add(min(adders, key=lambda v: (-v.trip.adds, *order(v))), "most adds")
    add(min(views, key=lambda v: (-v.trip.return_pct, *order(v))), "best return on notional")
    add(min(views, key=lambda v: (v.trip.return_pct, *order(v))), "worst return on notional")
    for v in sorted(views, key=lambda v: (-v.trip.closed_ms, v.trip.coin)):   # fill with the newest
        add(v, "recent trip")

    return [TradeExample(
        coin=v.trip.coin, side=v.trip.side, opened_ms=v.trip.opened_ms, closed_ms=v.trip.closed_ms,
        hold_h=round(v.trip.hold_h, 3), adds=v.trip.adds, max_leverage=v.leverage,
        net_pnl_usd=round(v.trip.net_pnl_usd, 2), return_pct=round(v.trip.return_pct, 3),
        context=v.ctx, why_shown=why) for v, why in chosen]


# ── the fingerprint ───────────────────────────────────────────────────────

def build_fingerprint(address: str, fills: Sequence[Dict[str, Any]],
                      bars_by_coin: Dict[str, Optional[Bars]], equity_points: Sequence[Point],
                      window_days: int, now_ms: int,
                      extra_caveats: Sequence[str] = ()) -> StrategyFingerprint:
    """Everything deterministic. `fills` should already be the window's
    fills; trips opened before now - window_days are dropped anyway.
    `bars_by_coin[coin]` None (or absent) means no candles for that coin."""
    from .template import render_summary  # template imports this module's helpers

    ws = now_ms - window_days * C.DAY_MS
    window_fills = [f for f in fills if ws <= int(f["time_ms"]) <= now_ms]
    all_trips, still_open = build_trips(window_fills)
    trips = [t for t in all_trips if t.opened_ms >= ws]
    n = len(trips)

    views: List[TripView] = []
    for t in trips:
        ctx = entry_context(bars_by_coin.get(t.coin), t.side, t.opened_ms, t.open_px)
        eq = equity_at(equity_points, t.opened_ms)
        v = TripView(trip=t, ctx=ctx)
        if eq:
            v.leverage = _r(t.max_notional_usd / eq)
            v.pct_of_equity = t.net_pnl_usd / eq * 100.0
        views.append(v)

    holds = [t.hold_h for t in trips]
    median_hold = _r(statistics.median(holds), 3) if holds else None
    opens_per_day = (n + still_open) / window_days if window_days > 0 else 0.0
    style = classify_style(opens_per_day, median_hold, n)

    trend = [v.ctx.trend_aligned for v in views if v.ctx.trend_aligned is not None]
    brk = [v.ctx.breakout for v in views if v.ctx.breakout is not None]
    pb = [v.ctx.pullback for v in views if v.ctx.pullback is not None]
    rsi_l = [v.ctx.rsi_14 for v in views if v.trip.side == "long" and v.ctx.rsi_14 is not None]
    rsi_s = [v.ctx.rsi_14 for v in views if v.trip.side == "short" and v.ctx.rsi_14 is not None]
    context_n = len(trend)

    wins = [t for t in trips if t.net_pnl_usd > 0]
    losses = [t for t in trips if t.net_pnl_usd < 0]
    avg_win = statistics.fmean(t.net_pnl_usd for t in wins) if wins else None
    avg_loss = statistics.fmean(t.net_pnl_usd for t in losses) if losses else None
    payoff = avg_win / abs(avg_loss) if (avg_win is not None and avg_loss) else None
    mw = statistics.median(t.hold_h for t in wins) if wins else None
    ml = statistics.median(t.hold_h for t in losses) if losses else None
    loser_vs_winner = ml / mw if (ml is not None and mw) else None

    levs = [v.leverage for v in views if v.leverage is not None]
    eq_pcts = [v.pct_of_equity for v in views if v.pct_of_equity is not None]

    hour_hist = [0] * 24
    weekday_hist = [0] * 7
    by_dow_hour = [[0] * 24 for _ in range(7)]   # [weekday][hour], UTC, Monday first
    for t in trips:
        h, d = hour_utc(t.opened_ms), weekday(t.opened_ms)
        hour_hist[h] += 1
        weekday_hist[d] += 1
        by_dow_hour[d][h] += 1
    session_start, session_pct = best_session(hour_hist)

    stats = coin_stats(window_fills, trips)
    top_coin, top_coin_pct = top_profit_coin(stats)
    top = stats[:C.TOP_COINS]
    if top_coin is not None and all(s.coin != top_coin for s in top):
        top.append(next(s for s in stats if s.coin == top_coin))

    fields: Dict[str, Any] = dict(
        trips_analyzed=n, style=style, median_hold_h=median_hold, p90_hold_h=_r(p90(holds), 3),
        long_pct=_pct(sum(1 for t in trips if t.side == "long"), n),
        trend_aligned_pct=_pct(sum(trend), len(trend)),
        breakout_pct=_pct(sum(brk), len(brk)),
        pullback_pct=_pct(sum(pb), len(pb)),
        avg_rsi_long_entry=_r(statistics.fmean(rsi_l)) if rsi_l else None,
        avg_rsi_short_entry=_r(statistics.fmean(rsi_s)) if rsi_s else None,
        avg_adds_per_trip=_r(statistics.fmean(t.adds for t in trips)) if trips else None,
        scales_in_pct=_pct(sum(1 for t in trips if t.adds >= 1), n),
        scales_out_pct=_pct(sum(1 for t in trips if t.exits >= 2), n),
        avg_leverage=_r(statistics.fmean(levs)) if levs else None,
        max_leverage=_r(max(levs)) if levs else None,
        win_rate_pct=_pct(len(wins), n),
        avg_win_usd=_r(avg_win), avg_loss_usd=_r(avg_loss), payoff_ratio=_r(payoff, 3),
        loser_hold_vs_winner=_r(loser_vs_winner, 3),
        worst_trip_pct_of_equity=_r(min(eq_pcts), 3) if eq_pcts else None,
        pnl_from_top_coin_pct=top_coin_pct,
        hour_hist_utc=hour_hist, weekday_hist=weekday_hist,
        entries_by_dow_hour=by_dow_hour, top_coins=top,
    )
    metrics = {k: v for k, v in fields.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    metrics["session_pct"] = session_pct
    tags = assign_tags(metrics, n, context_n)

    caveats = build_caveats(n, views, still_open, equity_points, window_fills, ws, window_days,
                            opens_per_day, bool(levs))
    caveats.extend(c for c in extra_caveats if c not in caveats)

    fp = StrategyFingerprint(
        address=address.lower(), as_of_ms=now_ms, window_days=window_days, tags=tags, summary="",
        examples=select_examples(views, tags, session_start), caveats=caveats, **fields)
    fp.summary = render_summary(fp)
    return fp


def build_caveats(n: int, views: Sequence[TripView], still_open: int, equity_points: Sequence[Point],
                  fills: Sequence[Dict[str, Any]], ws: int, window_days: int, opens_per_day: float,
                  has_leverage: bool) -> List[str]:
    out: List[str] = []
    if n == 0:
        out.append(f"No closed round trips in the last {window_days} days, so there is nothing to fingerprint yet.")
    elif n < C.MIN_TRIPS_FOR_TAGS:
        out.append(f"Only {n} closed trips in {window_days} days: too few to tag a habit, so no tags.")
    elif n < C.SMALL_SAMPLE_TRIPS:
        out.append(f"Only {n} closed trips in {window_days} days. Treat the percentages as a sketch, "
                   "not a pattern.")
    missing = [v for v in views if v.ctx.trend_aligned is None]
    if missing:
        coins = sorted({v.trip.coin for v in missing})
        shown = ", ".join(coins[:6]) + (f" and {len(coins) - 6} more" if len(coins) > 6 else "")
        out.append(f"No usable 1h candles for {len(missing)} of {n} trips ({shown}). Entry habits use the "
                   f"other {n - len(missing)}.")
    if still_open:
        out.append(f"{still_open} position{'s' if still_open != 1 else ''} opened in the window "
                   f"{'are' if still_open != 1 else 'is'} still open and not counted.")
    if n and not any(v > 0 for _, v in equity_points):
        out.append("Account value history unavailable: leverage and worst trip vs equity are blank.")
    elif has_leverage:
        out.append("Leverage here is effective leverage (peak position notional / account value at entry), "
                   "not the exchange setting.")
    if fills_truncated(fills, ws):
        out.append(f"Hyperliquid serves only the newest {C.FILLS_CAP:,} fills and this wallet hit the cap, "
                   f"so the data starts later than {window_days} days ago.")
    if window_days * 24 > C.HL_MAX_BARS:
        out.append(f"1h candles reach back about {C.HL_MAX_BARS // 24} days; older entries have no market "
                   "context.")
    if opens_per_day > C.ALGO_CAVEAT_OPENS_PER_DAY:
        out.append(f"{opens_per_day:.0f} opens per day looks automated; it cannot be followed by hand.")
    return out
