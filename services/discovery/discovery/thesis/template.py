"""Plain-English text from a StrategyFingerprint. String assembly only: no
AI, no clock, no randomness. Same fingerprint in, identical text out.

render_summary(fp)  -> 4 to 8 sentences (1 when there are no trips)
render_markdown(fp) -> the `ta` Thesis body

Rule for every sentence: it is emitted only when the numbers it quotes
exist, so a missing metric drops the sentence instead of printing "None".
No em dashes anywhere (test_thesis_template checks).
"""
from __future__ import annotations

import datetime as _dt
from typing import List, Optional, Sequence

from contracts.models import StrategyFingerprint, TradeExample

from . import config as C
from .fingerprint import best_session, top_profit_coin

_STYLE_WORD = {"algo": "algorithmic", "scalp": "scalping", "intraday": "intraday",
               "swing": "swing", "position": "position"}
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# tag -> lesson line for "What to learn". {placeholders} come from the fingerprint.
_LESSONS = {
    "trend follower": "Trade with the 1h EMA50 slope: {trend_aligned_pct:.0f}% of their entries do.",
    "counter-trend": "They fade the 1h trend ({trend_aligned_pct:.0f}% trend-aligned). That needs tight "
                     "risk; copy the exits, not just the entries.",
    "dip buyer": "Wait for a pullback inside the trend instead of chasing: {pullback_pct:.0f}% of entries "
                 "come 2%+ off the 20-bar extreme while still on the trend side of the EMA50.",
    "breakout buyer": "Enter as price presses the 20-bar high or low: {breakout_pct:.0f}% of entries are "
                      "breakouts.",
    "scales in": "Start small and add when the trade works: {scales_in_pct:.0f}% of trips get at least "
                 "one add.",
    "scales out": "Take profit in pieces: {scales_out_pct:.0f}% of trips close in two or more exits.",
    "runs winners": "Let winners run: the average win is {payoff_ratio:.1f}x the average loss.",
    "cuts losers fast": "Cut losers early: losing trips are held {loser_hold_vs_winner:.2f}x as long as "
                        "winners (median vs median).",
    "holds losers": "Warning, not a lesson: losers are held {loser_hold_vs_winner:.1f}x as long as "
                    "winners. Do not copy that habit.",
    "high win rate": "A high hit rate ({win_rate_pct:.0f}%) carries the edge; check the payoff before "
                     "assuming it scales.",
    "high leverage": "About {avg_leverage:.0f}x effective leverage: size down if you copy this.",
    "concentrated": "{pnl_from_top_coin_pct:.0f}% of profits came from one coin. The edge may be that "
                    "market, not the method.",
    "session trader": "Entries cluster in one 6h UTC session; the setup may only work in that liquidity.",
    "long biased": "Mostly long ({long_pct:.0f}% of trips). Results lean on the market going up.",
    "short biased": "Mostly short ({long_pct:.0f}% long). Results lean on the market going down.",
}


# ── formatting ────────────────────────────────────────────────────────────

def usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    a = abs(x)
    return f"{sign}${a:,.0f}" if a >= 100 else f"{sign}${a:,.2f}"


def hours(h: float) -> str:
    if h < 1:
        return f"{h * 60:.0f}m"
    if h < 48:
        return f"{h:.1f}h"
    return f"{h / 24:.1f}d"


def pct(x: float) -> str:
    return f"{x:.0f}%"


def join_words(items: Sequence[str]) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def utc_hhmm(h: int) -> str:
    return f"{h % 24:02d}:00"


def _date(ms: int) -> str:
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def main_coins(fp: StrategyFingerprint, k: int = 3) -> List[str]:
    """Up to k coins by volume, each with >= 10% of the listed volume."""
    total = sum(c.volume_usd for c in fp.top_coins)
    if total <= 0:
        return [c.coin for c in fp.top_coins[:1]]
    out = [c.coin for c in fp.top_coins if c.volume_usd / total >= 0.10][:k]
    return out or [fp.top_coins[0].coin]


def direction_word(long_pct: Optional[float]) -> str:
    if long_pct is None:
        return ""
    if long_pct >= 75:
        return " long"
    if long_pct <= 25:
        return " short"
    return ""


# ── summary ───────────────────────────────────────────────────────────────

def _headline(fp: StrategyFingerprint) -> str:
    adj = ""
    if "trend follower" in fp.tags:
        adj = "trend-following"
    elif "counter-trend" in fp.tags:
        adj = "counter-trend"
    style = _STYLE_WORD.get(fp.style.value if fp.style else "", "")
    words = " ".join(w for w in (adj, style, "trader") if w)
    coins = main_coins(fp)
    tail = f" on {join_words(coins)}" if coins else ""
    return words[0].upper() + words[1:] + tail + "."


def _entries(fp: StrategyFingerprint) -> List[str]:
    if fp.trend_aligned_pct is None:
        return []
    out: List[str] = []
    d = direction_word(fp.long_pct)
    pb, br = fp.pullback_pct or 0.0, fp.breakout_pct or 0.0
    if pb == 0 and br == 0:
        out.append("Entries are neither clean breakouts nor pullbacks on the 1h chart.")
    elif pb >= br:
        s = (f"Enters{d} on pullbacks that stay on the trend side of the 1h EMA50 ({pct(pb)} of trips)")
        out.append(s + (f"; {pct(br)} are breakouts of the 20-bar range." if br > 0 else "."))
    else:
        s = f"Enters{d} on breakouts of the 20-bar high or low ({pct(br)} of trips)"
        out.append(s + (f"; {pct(pb)} are pullback entries." if pb > 0 else "."))
    rsi = []
    if fp.avg_rsi_long_entry is not None:
        rsi.append(f"{fp.avg_rsi_long_entry:.0f} on longs")
    if fp.avg_rsi_short_entry is not None:
        rsi.append(f"{fp.avg_rsi_short_entry:.0f} on shorts")
    s = f"{pct(fp.trend_aligned_pct)} of entries go with the 1h EMA50 slope"
    out.append(s + (f", at an average 1h RSI of {join_words(rsi)}." if rsi else "."))
    return out


def _outcome(fp: StrategyFingerprint) -> List[str]:
    out: List[str] = []
    if fp.win_rate_pct is not None and fp.long_pct is not None:
        out.append(f"Wins {pct(fp.win_rate_pct)} of {fp.trips_analyzed} closed trips, "
                   f"{pct(fp.long_pct)} of them long.")
    if fp.payoff_ratio is not None and fp.avg_win_usd is not None and fp.avg_loss_usd is not None:
        tail = f"average win is {fp.payoff_ratio:.1f}x average loss ({usd(fp.avg_win_usd)} vs {usd(fp.avg_loss_usd)})"
        if "runs winners" in fp.tags:
            out.append(f"Lets winners run: {tail}.")
        elif fp.payoff_ratio < 1:
            out.append(f"The {tail}, so the edge comes from the hit rate.")
        else:
            out.append(f"The {tail}.")
    elif fp.avg_win_usd is not None and fp.avg_loss_usd is None:
        out.append(f"No losing trips in the window; the average win is {usd(fp.avg_win_usd)}.")
    return out


def _holds(fp: StrategyFingerprint) -> List[str]:
    if fp.median_hold_h is None:
        return []
    s = f"Median hold is {hours(fp.median_hold_h)}"
    if fp.p90_hold_h is not None:
        s += f" (90% of trips close within {hours(fp.p90_hold_h)})"
    r = fp.loser_hold_vs_winner
    if r is not None:
        if r < 0.05:
            s += "; losers are closed almost at once, at under 5% of a winner's hold"
        else:
            s += f"; losers are held {r:.2f}x as long as winners"
    return [s + "."]


def _sizing(fp: StrategyFingerprint) -> List[str]:
    out: List[str] = []
    if fp.scales_in_pct is not None and fp.scales_out_pct is not None:
        if fp.scales_in_pct == 0 and fp.scales_out_pct == 0:
            out.append("Goes in and out in one piece: no adds, single exits.")
        else:
            ins = (f"Adds to {pct(fp.scales_in_pct)} of trips ({fp.avg_adds_per_trip or 0:.1f} adds on average)"
                   if fp.scales_in_pct > 0 else "Never adds to a trip")
            outs = (f"scales out of {pct(fp.scales_out_pct)}" if fp.scales_out_pct > 0
                    else "exits each in one piece")
            out.append(f"{ins} and {outs}.")
    if fp.avg_leverage is not None and fp.max_leverage is not None:
        s = (f"Runs about {fp.avg_leverage:.1f}x effective leverage on average, peaking at "
             f"{fp.max_leverage:.1f}x")
        if fp.worst_trip_pct_of_equity is not None and fp.worst_trip_pct_of_equity < 0:
            s += f"; the worst trip cost {abs(fp.worst_trip_pct_of_equity):.1f}% of the account"
        out.append(s + ".")
    return out


def _timing(fp: StrategyFingerprint) -> List[str]:
    out: List[str] = []
    start, share = best_session(fp.hour_hist_utc)
    if share is not None and "session trader" in fp.tags:
        out.append(f"{pct(share)} of entries fall between {utc_hhmm(start)} and "
                   f"{utc_hhmm(start + C.SESSION_HOURS)} UTC.")
    coin, _ = top_profit_coin(fp.top_coins)
    if coin is not None and fp.pnl_from_top_coin_pct is not None and fp.pnl_from_top_coin_pct >= 50:
        out.append(f"{pct(fp.pnl_from_top_coin_pct)} of realized profit came from {coin}.")
    return out


def render_summary(fp: StrategyFingerprint) -> str:
    if fp.trips_analyzed == 0:
        return (f"No closed round trips in the last {fp.window_days} days, so there is no strategy to "
                "describe yet.")
    parts = [_headline(fp)] + _entries(fp) + _outcome(fp) + _holds(fp) + _sizing(fp) + _timing(fp)
    return " ".join(parts[:C.MAX_SUMMARY_SENTENCES])


# ── markdown ──────────────────────────────────────────────────────────────

def _yn(v: Optional[bool]) -> str:
    return "-" if v is None else ("yes" if v else "no")


def _num(v: Optional[float], fmt: str = "{:.0f}") -> str:
    return "-" if v is None else fmt.format(v)


def _example_row(e: TradeExample) -> str:
    c = e.context
    return (f"| {e.why_shown} | {e.coin} {e.side} | {_date(e.opened_ms)} | {hours(e.hold_h)} | {e.adds} | "
            f"{_num(e.max_leverage, '{:.1f}x')} | {usd(e.net_pnl_usd)} | {e.return_pct:+.2f}% | "
            f"{_yn(c.trend_aligned)} | {_yn(c.pullback)} | {_yn(c.breakout)} | {_num(c.rsi_14)} | "
            f"{_num(c.move_24h_pct, '{:+.1f}%')} |")


def render_markdown(fp: StrategyFingerprint) -> str:
    L: List[str] = []
    L.append("## How they trade")
    L.append(fp.summary)
    if fp.tags:
        L.append("")
        L.append("Tags: " + ", ".join(f"`{t}`" for t in fp.tags))
    L.append("")
    L.append("## Entries")
    if fp.trend_aligned_pct is None:
        L.append("- No 1h candle context for these entries.")
    else:
        L.append(f"- With the 1h EMA50 slope: {pct(fp.trend_aligned_pct)} of trips")
        L.append(f"- Pullback entries (2%+ off the 20-bar extreme, trend side of EMA50): "
                 f"{_num(fp.pullback_pct, '{:.0f}%')}")
        L.append(f"- Breakout entries (within 0.5% of the 20-bar high or low): {_num(fp.breakout_pct, '{:.0f}%')}")
        L.append(f"- Average 1h RSI at entry: longs {_num(fp.avg_rsi_long_entry)}, shorts "
                 f"{_num(fp.avg_rsi_short_entry)}")
    L.append(f"- Long share: {_num(fp.long_pct, '{:.0f}%')}")
    L.append("")
    L.append("## Sizing & risk")
    L.append(f"- Trips with at least one add: {_num(fp.scales_in_pct, '{:.0f}%')} "
             f"(avg {_num(fp.avg_adds_per_trip, '{:.1f}')} adds)")
    L.append(f"- Trips closed in 2+ exits: {_num(fp.scales_out_pct, '{:.0f}%')}")
    L.append(f"- Effective leverage: avg {_num(fp.avg_leverage, '{:.1f}x')}, max {_num(fp.max_leverage, '{:.1f}x')}")
    L.append(f"- Win rate {_num(fp.win_rate_pct, '{:.0f}%')}; avg win "
             f"{usd(fp.avg_win_usd) if fp.avg_win_usd is not None else '-'}; avg loss "
             f"{usd(fp.avg_loss_usd) if fp.avg_loss_usd is not None else '-'}; payoff "
             f"{_num(fp.payoff_ratio, '{:.2f}')}")
    L.append(f"- Median loser hold / median winner hold: {_num(fp.loser_hold_vs_winner, '{:.2f}')}")
    L.append(f"- Worst trip vs account: {_num(fp.worst_trip_pct_of_equity, '{:+.2f}%')}")
    L.append(f"- Share of realized profit from the best coin: {_num(fp.pnl_from_top_coin_pct, '{:.0f}%')}")
    L.append("")
    L.append("## When")
    L.append(f"- Median hold {hours(fp.median_hold_h) if fp.median_hold_h is not None else '-'}, "
             f"p90 {hours(fp.p90_hold_h) if fp.p90_hold_h is not None else '-'}")
    start, share = best_session(fp.hour_hist_utc)
    if share is not None:
        L.append(f"- Busiest 6h window: {utc_hhmm(start)} to {utc_hhmm(start + C.SESSION_HOURS)} UTC "
                 f"({pct(share)} of entries)")
        top_hours = sorted(range(24), key=lambda h: (-fp.hour_hist_utc[h], h))[:3]
        L.append("- Top entry hours (UTC): " + ", ".join(f"{utc_hhmm(h)} ({fp.hour_hist_utc[h]})"
                                                          for h in top_hours))
    if sum(fp.weekday_hist):
        L.append("- Entries by weekday: " + ", ".join(f"{_WEEKDAYS[i][:3]} {n}" for i, n in
                                                      enumerate(fp.weekday_hist)))
    if fp.top_coins:
        L.append("- Coins: " + ", ".join(f"{c.coin} ({usd(c.volume_usd)} vol, {usd(c.pnl_usd)} PnL, "
                                         f"{c.trips} trips)" for c in fp.top_coins))
    L.append("")
    L.append("## What to learn")
    lessons = []
    vals = fp.model_dump()
    for t in fp.tags:
        tpl = _LESSONS.get(t)
        if tpl is None:
            continue
        try:
            lessons.append("- " + tpl.format(**{k: (v if v is not None else 0.0) for k, v in vals.items()}))
        except (KeyError, ValueError, TypeError):
            continue
    L.extend(lessons or ["- No habit crossed a tag threshold; nothing specific to copy yet."])
    L.append("")
    L.append("## Evidence")
    if fp.examples:
        L.append("| why | trade | opened (UTC) | hold | adds | lev | net | return | trend | pullback | "
                 "breakout | RSI | 24h move |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        L.extend(_example_row(e) for e in fp.examples)
    else:
        L.append("No trips to show.")
    L.append("")
    L.append("## Caveats")
    L.extend([f"- {c}" for c in fp.caveats] or ["- None."])
    L.append("")
    L.append(f"_Deterministic TA fingerprint over {fp.window_days} days, {fp.trips_analyzed} closed trips, "
             f"as of {_date(fp.as_of_ms)} UTC. No AI._")
    return "\n".join(L)


def render_title(fp: StrategyFingerprint) -> str:
    return "TA fingerprint: " + _headline(fp).rstrip(".")
