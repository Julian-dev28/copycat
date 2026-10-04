"""Template determinism and wording: same input, identical text; 4 to 8
sentences; no em or en dashes; every markdown section present."""
from __future__ import annotations

import re

from discovery.thesis import config as C
from discovery.thesis.fingerprint import build_fingerprint
from discovery.thesis.template import hours, join_words, render_markdown, render_summary, usd
from test_thesis_fixtures import ADDR, T0, D, H, bars_from_closes, trip_fills

from contracts.models import CoinStat, StrategyFingerprint, TradingStyle

SECTIONS = ["## How they trade", "## Entries", "## Sizing & risk", "## When", "## What to learn",
            "## Evidence", "## Caveats"]


def sentences(text: str) -> int:
    return len(re.findall(r"\.(?:\s|$)", text))


def built():
    """BTC and HYPE longs entering on pullbacks in a slow 1h uptrend."""
    closes = [100 * (1.002 ** i) for i in range(24 * 40)]
    bars = {"BTC": bars_from_closes(closes), "HYPE": bars_from_closes(closes)}
    fills = []
    for k in range(12):
        coin = "BTC" if k % 2 else "HYPE"
        o = T0 + (300 + k * 40) * H
        i = (o - T0) // H - 1                     # last closed bar
        px = closes[i] * 1.001 * 0.975            # 2.5% under the 20-bar high, above EMA50
        out = px * (1.04 if k % 3 else 0.99)
        fills += trip_fills(coin, "long", o, px, o + (20 if k % 3 else 6) * H, out,
                            adds=[(o + 2 * H, 0.5, px * 1.01)] if k % 2 else ())
    return build_fingerprint(ADDR, fills, bars, [(T0, 5_000.0)], 60, T0 + 40 * D)


def manual(**kw) -> StrategyFingerprint:
    base = dict(address=ADDR, as_of_ms=T0, window_days=30, trips_analyzed=40, style=TradingStyle.swing,
                median_hold_h=30.0, p90_hold_h=96.0, long_pct=80.0, trend_aligned_pct=70.0, breakout_pct=10.0,
                pullback_pct=62.0, avg_rsi_long_entry=48.2, avg_rsi_short_entry=61.0, avg_adds_per_trip=1.3,
                scales_in_pct=55.0, scales_out_pct=30.0, avg_leverage=8.0, max_leverage=22.0,
                win_rate_pct=58.0, avg_win_usd=1234.0, avg_loss_usd=-440.0, payoff_ratio=2.8,
                loser_hold_vs_winner=0.4, worst_trip_pct_of_equity=-4.1, pnl_from_top_coin_pct=72.0,
                hour_hist_utc=[0] * 13 + [10] * 6 + [0] * 5, weekday_hist=[6] * 7,
                top_coins=[CoinStat(coin="BTC", volume_usd=9e6, pnl_usd=5e4, trips=25),
                           CoinStat(coin="HYPE", volume_usd=3e6, pnl_usd=1e4, trips=15)],
                tags=["trend follower", "dip buyer", "scales in", "runs winners", "cuts losers fast",
                      "concentrated", "session trader", "long biased"], summary="")
    base.update(kw)
    return StrategyFingerprint(**base)


def test_same_input_identical_text():
    a, b = built(), built()
    assert a.summary == b.summary and render_markdown(a) == render_markdown(b)
    assert a.model_dump_json() == b.model_dump_json()
    assert render_summary(a) == a.summary                    # regenerable from the stored fingerprint


def test_built_fingerprint_reads_like_the_strategy():
    fp = built()
    assert fp.trend_aligned_pct == 100.0 and fp.pullback_pct == 100.0 and fp.breakout_pct == 0.0
    assert "trend follower" in fp.tags and "dip buyer" in fp.tags
    assert fp.summary.startswith("Trend-following ")
    assert " on HYPE and BTC." in fp.summary or " on BTC and HYPE." in fp.summary
    assert "Enters long on pullbacks" in fp.summary
    assert 4 <= sentences(fp.summary) <= C.MAX_SUMMARY_SENTENCES


def test_manual_summary_wording():
    s = render_summary(manual())
    assert s.startswith("Trend-following swing trader on BTC and HYPE.")
    assert "Enters long on pullbacks that stay on the trend side of the 1h EMA50 (62% of trips); " \
           "10% are breakouts of the 20-bar range." in s
    assert "Lets winners run: average win is 2.8x average loss ($1,234 vs -$440)." in s
    assert 4 <= sentences(s) <= 8


def test_summary_sentence_bounds_and_missing_metrics():
    sparse = manual(trend_aligned_pct=None, breakout_pct=None, pullback_pct=None, avg_leverage=None,
                    max_leverage=None, tags=[], style=None)
    s = render_summary(sparse)
    assert s.startswith("Trader on BTC and HYPE.")
    assert "None" not in s and 4 <= sentences(s) <= 8
    empty = manual(trips_analyzed=0)
    assert sentences(render_summary(empty)) == 1


def test_no_dashes_anywhere():
    for fp in (built(), manual(), manual(tags=list(t for t, *_ in C.TAG_RULES))):
        text = render_summary(fp) + render_markdown(fp)
        assert "—" not in text and "–" not in text


def test_markdown_sections_and_lessons():
    md = render_markdown(manual(tags=[t for t, *_ in C.TAG_RULES]))
    pos = [md.index(s) for s in SECTIONS]
    assert pos == sorted(pos)
    assert md.count("\n- ") > 20                              # one lesson per tag, plus the facts
    ev = render_markdown(built())
    assert "| why | trade |" in ev and "largest win" in ev


def test_formatters():
    assert usd(1234.4) == "$1,234" and usd(-440) == "-$440" and usd(12.5) == "$12.50"
    assert hours(0.5) == "30m" and hours(6.25) == "6.2h" and hours(72) == "3.0d"
    assert join_words(["A"]) == "A" and join_words(["A", "B", "C"]) == "A, B and C"


def test_regression_wording_from_live_eval():
    """Live eval 2026-10-04: a leader whose losers close in seconds printed
    'losers are held 0.00x as long as winners', and 'scales out of 0%'."""
    s = render_summary(manual(loser_hold_vs_winner=0.001, scales_out_pct=0.0))
    assert "0.00x" not in s and "losers are closed almost at once" in s
    assert "scales out of 0%" not in s and "exits each in one piece" in s
    s = render_summary(manual(scales_in_pct=0.0, avg_adds_per_trip=0.0, scales_out_pct=25.0))
    assert "Never adds to a trip and scales out of 25%." in s
