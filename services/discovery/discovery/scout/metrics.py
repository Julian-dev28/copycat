"""Pure metric math for Scout (spec section 2). No I/O, no clock: every
function takes its inputs (and `now_ms` where time matters) explicitly, so
the same input always gives the same number.

Portfolio metrics (#8 to #14) work on HL `portfolio` histories:
`[[t_ms, "value"], ...]` per window. Daily resample = the last point of each
UTC day that HAS a point ("observed day close"). Returns run between
consecutive observed closes:

    r = (P_d - P_prev) / AV_prev        skipped when AV_prev < 100

The month and week windows have a point every day, so this is exactly the
spec's daily return. allTime is sparser (~1 point per 2 to 3 days, measured
2026-10-04); there the ratio is annualised by the mean gap
(`sqrt(365 / mean_gap_days)`), which reduces to the spec's `sqrt(365)` when
every day is observed. That is the one deliberate extension of the spec
formula; without it a 3-day return would be annualised as if daily.

Trade metrics (#15 to #22) work on raw perp fills, NOT poll-coalesced: they
describe the leader, not what our copy would see.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from contracts.models import (
    AccountRisk,
    CoinStat,
    CurvePoint,
    PnlTier,
    PnlWindow,
    RiskStats,
    RoundTrip,
    SizeTier,
    TraderPositionView,
    TradeStats,
    TradingStyle,
)

from .. import positions
from . import config as C

Point = Tuple[int, float]

PORTFOLIO_WINDOWS = {"day": PnlWindow.day, "week": PnlWindow.week, "month": PnlWindow.month,
                     "allTime": PnlWindow.all_time}
WINDOW_DAYS = {PnlWindow.day: 1, PnlWindow.week: 7, PnlWindow.month: 30}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ── portfolio parsing ─────────────────────────────────────────────────────

def parse_portfolio(raw: Optional[Sequence[Any]]) -> Dict[str, Dict[str, Any]]:
    """HL portfolio -> {window_name: {"pnl": [(t, v)], "av": [(t, v)], "vlm": float}}.
    Unparseable points are dropped; points are sorted by time."""
    out: Dict[str, Dict[str, Any]] = {}
    for pair in raw or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[1], dict)):
            continue
        name, body = pair

        def series(key: str, body: Dict[str, Any] = body) -> List[Point]:
            pts = []
            for p in body.get(key) or []:
                if isinstance(p, (list, tuple)) and len(p) == 2:
                    t, v = _num(p[0]), _num(p[1])
                    if t is not None and v is not None:
                        pts.append((int(t), v))
            pts.sort()
            return pts

        out[str(name)] = {"pnl": series("pnlHistory"), "av": series("accountValueHistory"),
                          "vlm": _num(body.get("vlm")) or 0.0}
    return out


def day_closes(points: Sequence[Point]) -> List[Point]:
    """Last value of each UTC day that has a point; t = that day's UTC midnight."""
    closes: Dict[int, float] = {}
    for t, v in sorted(points):
        closes[(t // C.DAY_MS) * C.DAY_MS] = v
    return sorted(closes.items())


def _value_at(closes: Sequence[Point], day_t: int) -> Optional[float]:
    """Latest close at or before day_t (carry forward), None before the first."""
    best = None
    for t, v in closes:
        if t > day_t:
            break
        best = v
    return best


@dataclass
class DailyReturns:
    days: List[int]          # day t of each return (the later close)
    returns: List[float]
    gaps: List[float]        # days between the two closes


def daily_returns(pnl: Sequence[Point], av: Sequence[Point]) -> DailyReturns:
    """#8. r_d = (P_d - P_prev) / capital over consecutive observed day
    closes; skipped when AV_prev < MIN_AV_FOR_RETURN (the day is dropped,
    the next return still starts from it).

    capital = AV_prev + max(0, net deposits in the step), where net deposits
    = (AV_d - AV_prev) - (P_d - P_prev): the account value change that PnL
    does not explain. Money deposited during the step is at risk in it, so a
    loss on it is measured against it, not against the (possibly tiny)
    balance before the deposit. r is floored at -100%: an account cannot lose
    more than the capital it had.
    Regression: a +$61M trader showed "all-time max drawdown 100%" because a
    loss on freshly deposited millions was divided by a ~$1k prior balance
    (r = -2000%), which drove the drawdown index below zero."""
    p = day_closes(pnl)
    a = day_closes(av)
    out = DailyReturns([], [], [])
    for (t0, p0), (t1, p1) in zip(p, p[1:], strict=False):
        av0 = _value_at(a, t0)
        if av0 is None or av0 < C.MIN_AV_FOR_RETURN:
            continue
        av1 = _value_at(a, t1)
        inflow = max(0.0, (av1 - av0) - (p1 - p0)) if av1 is not None else 0.0
        out.days.append(t1)
        out.returns.append(max(-1.0, (p1 - p0) / (av0 + inflow)))
        out.gaps.append((t1 - t0) / C.DAY_MS)
    return out


def max_drawdown_pct(returns: Sequence[float]) -> Optional[float]:
    """#9. I_0 = 1, I_d = I_{d-1}(1 + r_d); worst I_d / peak - 1, as a positive %.
    Always in [0, 100]: r is floored at -100% (an index below zero would read
    as a drawdown past 100%)."""
    if not returns:
        return None
    idx, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        idx *= (1.0 + max(-1.0, r))
        peak = max(peak, idx)
        worst = min(worst, idx / peak - 1.0)
    return -worst * 100.0


def _ann(gaps: Sequence[float]) -> float:
    g = sum(gaps) / len(gaps) if gaps else 1.0
    return math.sqrt(365.0 / g) if g > 0 else math.sqrt(365.0)


def sharpe(returns: Sequence[float], gaps: Optional[Sequence[float]] = None) -> Optional[float]:
    """#10. mean / stdev(ddof=1) * sqrt(365); null below 7 returns or stdev 0."""
    if len(returns) < C.MIN_DAYS_FOR_RATIO:
        return None
    sd = statistics.stdev(returns)
    if sd == 0:
        return None
    return statistics.fmean(returns) / sd * _ann(gaps or [1.0])


def sortino(returns: Sequence[float], gaps: Optional[Sequence[float]] = None) -> Optional[float]:
    """#11. mean / sqrt(mean(min(r,0)^2)) * sqrt(365); null with no negative
    return, and (like sharpe) below 7 returns."""
    if len(returns) < C.MIN_DAYS_FOR_RATIO or not any(r < 0 for r in returns):
        return None
    dd = math.sqrt(statistics.fmean([min(r, 0.0) ** 2 for r in returns]))
    return statistics.fmean(returns) / dd * _ann(gaps or [1.0])


def profitable_days_pct(returns: Sequence[float]) -> Optional[float]:
    """#12."""
    if not returns:
        return None
    return sum(1 for r in returns if r > 0) / len(returns) * 100.0


def risk_stats(window: PnlWindow, pnl: Sequence[Point], av: Sequence[Point]) -> RiskStats:
    dr = daily_returns(pnl, av)
    return RiskStats(window=window, max_drawdown_pct=_r(max_drawdown_pct(dr.returns)),
                     sharpe=_r(sharpe(dr.returns, dr.gaps)), sortino=_r(sortino(dr.returns, dr.gaps)),
                     profitable_days_pct=_r(profitable_days_pct(dr.returns)), days=len(dr.returns))


def daily_pnl(port: Dict[str, Dict[str, Any]], now_ms: int, days: int = C.CALENDAR_DAYS) -> List[CurvePoint]:
    """#14. PnL per UTC day, P_d - P_{d-1}, last `days` days. Each day uses
    the densest window that has closes for both d-1 and d (week, then month,
    then allTime). Windows have different baselines, so only within-window
    differences are taken, never levels across windows."""
    per_day: Dict[int, float] = {}
    for name in ("allTime", "month", "week"):          # later (denser) windows overwrite
        closes = day_closes((port.get(name) or {}).get("pnl") or [])
        for (t0, p0), (t1, p1) in zip(closes, closes[1:], strict=False):
            if t1 - t0 == C.DAY_MS:
                per_day[t1] = p1 - p0
            elif name == "allTime" and t1 not in per_day:
                per_day[t1] = p1 - p0                  # multi-day step lands on its close day
    lo = (now_ms // C.DAY_MS) * C.DAY_MS - (days - 1) * C.DAY_MS
    return [CurvePoint(t_ms=t, value=round(v, 2)) for t, v in sorted(per_day.items()) if t >= lo]


def longest_win_streak_days(calendar: Sequence[CurvePoint]) -> int:
    """#13. Longest run of consecutive calendar days with PnL > 0. A missing
    day breaks the run (no data is not a win)."""
    best = run = 0
    prev_t: Optional[int] = None
    for p in calendar:
        if p.value > 0:
            run = run + 1 if (prev_t is not None and p.t_ms - prev_t == C.DAY_MS and run > 0) else 1
            best = max(best, run)
        else:
            run = 0
        prev_t = p.t_ms
    return best


def curve(points: Sequence[Point]) -> List[CurvePoint]:
    return [CurvePoint(t_ms=t, value=round(v, 2)) for t, v in points]


def downsample(points: Sequence[CurvePoint], max_points: int = C.SPARK_MAX_POINTS) -> List[CurvePoint]:
    """Evenly spaced picks, first and last always kept."""
    n = len(points)
    if n <= max_points:
        return list(points)
    idx = sorted({round(i * (n - 1) / (max_points - 1)) for i in range(max_points)})
    return [points[i] for i in idx]


def window_perf_from_portfolio(port: Dict[str, Dict[str, Any]], name: str) -> Tuple[float, float, float]:
    """(pnl, roi_pct, vlm) for a wallet not on the leaderboard: pnl = last
    pnlHistory point, roi = pnl / first accountValue point. Approximate (HL's
    own roi accounts for deposits); used only for on-demand trader files."""
    w = port.get(name) or {}
    pnl = w["pnl"][-1][1] if w.get("pnl") else 0.0
    av0 = w["av"][0][1] if w.get("av") else 0.0
    return pnl, (pnl / av0 * 100.0 if av0 > 0 else 0.0), float(w.get("vlm") or 0.0)


# ── round trips (#15 to #19) ──────────────────────────────────────────────

def round_trips(fills: Sequence[Dict[str, Any]], funding: Optional[Sequence[Dict[str, Any]]] = None) -> List[RoundTrip]:
    """Flat to flat per coin over perp fills (`positions.reconstruct`, so a
    flip is a close then an open). A trip already open at the first fill we
    have, or still open at the last, is dropped: it is never fabricated.
    gross = sum(closed_pnl) over the trip's fills (on a flip the fill's fee
    and closed_pnl belong to the closing trip); funding = net HL `userFunding`
    settled for the coin while this trip's position was open
    (`positions.funding_by_trip`), 0 when `funding` is None (not fetched).
    net = gross - fee + funding."""
    perp, _ = positions.split_perp(list(fills))
    funding_idx = positions.index_funding_by_coin(funding)
    trips: List[RoundTrip] = []
    for coin, events in positions.reconstruct(perp).items():
        cur: Optional[Dict[str, Any]] = None
        for e in events:
            if e.kind == "open":
                cur = {"side": e.side, "opened": e.time_ms, "in_sz": e.delta_sz, "in_ntl": e.delta_sz * e.px,
                       "out_sz": 0.0, "out_ntl": 0.0, "pnl": e.closed_pnl, "fee": e.fee,
                       "max_ntl": abs(e.end_position) * e.px}
                continue
            if cur is None:
                continue                     # trip began before our first fill
            cur["pnl"] += e.closed_pnl
            cur["fee"] += e.fee
            if e.kind == "add":
                cur["in_sz"] += e.delta_sz
                cur["in_ntl"] += e.delta_sz * e.px
            else:
                cur["out_sz"] += e.delta_sz
                cur["out_ntl"] += e.delta_sz * e.px
            cur["max_ntl"] = max(cur["max_ntl"], abs(e.end_position) * e.px, abs(e.start_position) * e.px)
            if e.kind == "close":
                fund = positions.funding_by_trip(funding_idx, coin, cur["opened"], e.time_ms)
                net = cur["pnl"] - cur["fee"] + fund
                trips.append(RoundTrip(
                    coin=coin, side=cur["side"], opened_ms=cur["opened"], closed_ms=e.time_ms,
                    hold_h=round((e.time_ms - cur["opened"]) / C.HOUR_MS, 6),
                    entry_px=cur["in_ntl"] / cur["in_sz"] if cur["in_sz"] else e.px,
                    exit_px=cur["out_ntl"] / cur["out_sz"] if cur["out_sz"] else e.px,
                    max_notional_usd=round(cur["max_ntl"], 2), gross_pnl_usd=round(cur["pnl"], 6),
                    fee_usd=round(cur["fee"], 6), funding_usd=round(fund, 6),
                    net_pnl_usd=round(net, 6), win=net > 0))
                cur = None
    trips.sort(key=lambda t: (t.closed_ms, t.coin))
    return trips


def opens_in(fills: Sequence[Dict[str, Any]], start_ms: int) -> int:
    perp, _ = positions.split_perp(list(fills))
    return sum(1 for evs in positions.reconstruct(perp).values() for e in evs
               if e.kind == "open" and e.time_ms >= start_ms)


def trade_stats(window: PnlWindow, trips: Sequence[RoundTrip], fills: Sequence[Dict[str, Any]],
                now_ms: int) -> TradeStats:
    """Trips fully inside [now - W, now]."""
    days = WINDOW_DAYS[window]
    ws = now_ms - days * C.DAY_MS
    inside = [t for t in trips if t.opened_ms >= ws and t.closed_ms <= now_ms]
    holds = [t.hold_h for t in inside]
    wins = sum(1 for t in inside if t.win)
    return TradeStats(
        window=window, trips=len(inside), wins=wins,
        long_trips=sum(1 for t in inside if t.side == "long"),
        short_trips=sum(1 for t in inside if t.side == "short"),
        win_rate_pct=_r(wins / len(inside) * 100.0) if inside else None,
        avg_hold_h=_r(statistics.fmean(holds)) if holds else None,
        median_hold_h=_r(statistics.median(holds)) if holds else None,
        opens_per_day=round(opens_in(fills, ws) / days, 3))


def classify_style(opens_per_day: float, median_hold_h: Optional[float], trips: int) -> Optional[TradingStyle]:
    """#20. algo above 100 opens/day; else by median hold (scalp < 15 min,
    intraday < 24 h, swing < 7 d, position >= 7 d); null under 3 trips."""
    if opens_per_day > C.STYLE_ALGO_OPENS_PER_DAY:
        return TradingStyle.algo
    if trips < C.STYLE_MIN_TRIPS or median_hold_h is None:
        return None
    if median_hold_h < C.STYLE_SCALP_H:
        return TradingStyle.scalp
    if median_hold_h < C.STYLE_INTRADAY_H:
        return TradingStyle.intraday
    if median_hold_h < C.STYLE_SWING_H:
        return TradingStyle.swing
    return TradingStyle.position


def coin_stats(fills: Sequence[Dict[str, Any]], trips: Sequence[RoundTrip]) -> List[CoinStat]:
    """#21. Per perp coin: volume sum(px*sz), PnL sum(closed_pnl - fee), trips;
    ranked by volume desc (coin name breaks ties)."""
    perp, _ = positions.split_perp(list(fills))
    agg: Dict[str, List[float]] = {}
    for f in perp:
        a = agg.setdefault(f["coin"], [0.0, 0.0])
        a[0] += abs(float(f["px"]) * float(f["sz"]))
        a[1] += float(f.get("closed_pnl", 0.0)) - float(f.get("fee", 0.0))
    n_trips: Dict[str, int] = {}
    for t in trips:
        n_trips[t.coin] = n_trips.get(t.coin, 0) + 1
    out = [CoinStat(coin=c, volume_usd=round(v, 2), pnl_usd=round(p, 2), trips=n_trips.get(c, 0))
           for c, (v, p) in agg.items()]
    out.sort(key=lambda s: (-s.volume_usd, s.coin))
    return out


def hip3_share(coins: Sequence[CoinStat]) -> float:
    """Share of perp volume on HIP-3 (`dex:COIN`) markets, 0..1."""
    tot = sum(c.volume_usd for c in coins)
    return sum(c.volume_usd for c in coins if ":" in c.coin) / tot if tot > 0 else 0.0


def fills_truncated(fills: Sequence[Dict[str, Any]], window_start_ms: int) -> bool:
    """HL serves only the newest 10k fills: near that count with the oldest
    fill well after the window start means older fills are missing."""
    if len(fills) < C.TRUNCATED_MIN_FILLS:
        return False
    oldest = min(int(f["time_ms"]) for f in fills)
    return oldest > window_start_ms + C.DAY_MS


# ── account (#23 to #27) ──────────────────────────────────────────────────

def position_views(raw_positions: Dict[str, Dict[str, Any]]) -> List[TraderPositionView]:
    """clearinghouseState assetPositions[].position -> TraderPositionView.
    funding_since_open_usd is HL's cumFunding.sinceOpen as reported
    (HL's sign: positive = funding paid by the trader)."""
    out: List[TraderPositionView] = []
    for coin, p in sorted((raw_positions or {}).items()):
        szi = _num(p.get("szi")) or 0.0
        if szi == 0:
            continue
        ntl = abs(_num(p.get("positionValue")) or 0.0)
        mark = ntl / abs(szi) if szi else 0.0
        liq = _num(p.get("liquidationPx"))
        lev = p.get("leverage") or {}
        out.append(TraderPositionView(
            coin=coin, side="long" if szi > 0 else "short", size=szi, notional_usd=round(ntl, 2),
            entry_px=_num(p.get("entryPx")) or 0.0, mark_px=mark,
            unrealized_pnl_usd=round(_num(p.get("unrealizedPnl")) or 0.0, 2),
            roe_pct=round((_num(p.get("returnOnEquity")) or 0.0) * 100.0, 4),
            leverage=int(_num(lev.get("value")) or 1), is_cross=lev.get("type") == "cross",
            liquidation_px=liq if liq else None,
            liq_distance_pct=round(abs(mark - liq) / mark * 100.0, 4) if (liq and mark > 0) else None,
            margin_usd=round(_num(p.get("marginUsed")) or 0.0, 2),
            funding_since_open_usd=round(_num((p.get("cumFunding") or {}).get("sinceOpen")) or 0.0, 2),
            max_leverage=int(_num(p.get("maxLeverage")) or 0) or None))
    return out


def account_risk(state: Dict[str, Any], extras: Optional[Dict[str, Any]],
                 views: Sequence[TraderPositionView]) -> AccountRisk:
    """#24 leverage = gross / accountValue; #25 margin usage = sum(marginUsed)
    / accountValue; #26 nearest liq; #27 long share of gross. accountValue
    is perp equity; for a unified account with ~0 perp equity, perp + spot
    USDC (the collateral that actually backs the positions)."""
    perps = float(state.get("equity_perp_usd") or 0.0)
    spot_usdc = float(state.get("spot_usdc") or 0.0)
    ex = extras or {}
    base = perps if perps > 0 else perps + spot_usdc
    long_ntl = sum(v.notional_usd for v in views if v.side == "long")
    short_ntl = sum(v.notional_usd for v in views if v.side == "short")
    gross = long_ntl + short_ntl
    liqs = [v.liq_distance_pct for v in views if v.liq_distance_pct is not None]
    return AccountRisk(
        perps_usd=round(perps, 2), spot_usd=round(spot_usdc + float(ex.get("spot_other_usd") or 0.0), 2),
        staked_usd=round(float(ex.get("staked_hype_usd") or 0.0), 2),
        account_leverage=round(gross / base, 4) if base > 0 else 0.0,
        margin_usage_pct=round(sum(v.margin_usd for v in views) / base * 100.0, 4) if base > 0 else 0.0,
        nearest_liq_pct=min(liqs) if liqs else None,
        long_notional_usd=round(long_ntl, 2), short_notional_usd=round(short_ntl, 2),
        long_bias_pct=round(long_ntl / gross * 100.0, 4) if gross > 0 else None,
        unrealized_pnl_usd=round(sum(v.unrealized_pnl_usd for v in views), 2))


def bias_label(long_bias_pct: Optional[float]) -> Optional[str]:
    if long_bias_pct is None:
        return None
    if long_bias_pct >= 80:
        return "strongly long"
    if long_bias_pct >= 60:
        return "long"
    if long_bias_pct >= 40:
        return "balanced"
    if long_bias_pct >= 20:
        return "short"
    return "strongly short"


# ── tiers (#28, #29) ──────────────────────────────────────────────────────

def size_tier(account_value: float) -> SizeTier:
    if account_value < 10_000:
        return SizeTier.S
    if account_value < 100_000:
        return SizeTier.M
    if account_value < 1_000_000:
        return SizeTier.L
    if account_value < 10_000_000:
        return SizeTier.XL
    return SizeTier.XXL


def pnl_tier(pnl_all_time: float) -> PnlTier:
    if pnl_all_time < 0:
        return PnlTier.losing
    if pnl_all_time < 100_000:
        return PnlTier.up
    if pnl_all_time < 1_000_000:
        return PnlTier.strong
    return PnlTier.elite


def last_fill_ms(fills: Iterable[Dict[str, Any]]) -> Optional[int]:
    ts = [int(f["time_ms"]) for f in fills]
    return max(ts) if ts else None


def real_liquidations(fills: Iterable[Dict[str, Any]]) -> Tuple[int, Optional[int]]:
    """The wallet's OWN real liquidations in the given fills (HL's `dir` is
    "Liquidated Isolated Long/Short" or "Liquidated Cross Long/Short" on a
    liquidation fill; the venue layer's separate `liquidation` bool, when
    present, is not relied on here so this also works on fills cached before
    that field existed). Distinct from the copy-sim's own `sim_liquidations`:
    this says the trader himself got liquidated, whatever your settings are.
    Returns (count, last_ms); (0, None) when none in the given fills."""
    ts = [int(f["time_ms"]) for f in fills if str(f.get("dir") or "").startswith("Liquidated")]
    return len(ts), (max(ts) if ts else None)


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(x, nd)
