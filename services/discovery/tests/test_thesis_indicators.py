"""Entry-context math on hand-built 1h bars: EMA, RSI, trend alignment,
breakout, pullback, 24h move, look-ahead and staleness rules."""
from __future__ import annotations

import pytest
from discovery.thesis.indicators import ema, entry_context, hour_utc, rsi, weekday
from test_thesis_fixtures import T0, D, H, bars_from_closes

UP = [100 + 0.5 * i for i in range(100)]          # bar 99 closes 149.5, ends at T0 + 100h
DOWN = [200 - 0.5 * i for i in range(100)]
ENTRY = T0 + 100 * H


def test_ema_seeded_with_sma():
    assert ema([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]
    assert ema([1, 2], 3) == []


def test_rsi_values():
    assert rsi([10.0] * 20) == 50.0
    assert rsi([float(i) for i in range(20)]) == 100.0
    assert rsi([float(20 - i) for i in range(20)]) == 0.0
    closes = [10.0]
    for _ in range(7):
        closes += [closes[-1] + 2, closes[-1] + 1]     # +2, -1 alternating: avg gain 1, avg loss 0.5
    assert rsi(closes) == pytest.approx(100 - 100 / 3)
    assert rsi(closes[:14]) is None                    # needs 15 closes


def test_trend_aligned_long_uptrend_short_downtrend():
    up, down = bars_from_closes(UP), bars_from_closes(DOWN)
    assert entry_context(up, "long", ENTRY, 149.6).trend_aligned is True
    assert entry_context(up, "short", ENTRY, 149.6).trend_aligned is False
    assert entry_context(down, "short", ENTRY, 150.4).trend_aligned is True
    assert entry_context(down, "long", ENTRY, 150.4).trend_aligned is False


def test_breakout_long_at_20bar_high_and_short_at_low():
    up, down = bars_from_closes(UP), bars_from_closes(DOWN)
    ctx = entry_context(up, "long", ENTRY, 149.6)
    assert ctx.breakout is True and ctx.pullback is False
    hi20 = 149.5 * 1.001
    assert entry_context(up, "long", ENTRY, hi20 * 0.995).breakout is True       # exactly 0.5% under: edge in
    assert entry_context(up, "long", ENTRY, hi20 * 0.9949).breakout is False
    lo20 = 150.5 * 0.999
    assert entry_context(down, "short", ENTRY, lo20 * 1.005).breakout is True
    assert entry_context(down, "short", ENTRY, lo20 * 1.0051).breakout is False


def test_pullback_long_needs_2pct_off_high_and_above_ema():
    up = bars_from_closes(UP)
    hi20 = 149.5 * 1.001
    ctx = entry_context(up, "long", ENTRY, hi20 * 0.98)                 # 2% under: edge in
    assert ctx.pullback is True and ctx.breakout is False
    assert entry_context(up, "long", ENTRY, hi20 * 0.981).pullback is False
    assert entry_context(up, "long", ENTRY, 120.0).pullback is False     # under EMA50 (~137)


def test_pullback_short_mirror():
    down = bars_from_closes(DOWN)
    lo20 = 150.5 * 0.999
    assert entry_context(down, "short", ENTRY, lo20 * 1.02).pullback is True
    assert entry_context(down, "short", ENTRY, 180.0).pullback is False  # above EMA50


def test_rsi_and_move_24h_at_entry():
    ctx = entry_context(bars_from_closes(UP), "long", ENTRY, 149.6)
    assert ctx.rsi_14 == 100.0
    # bar closed at or before entry - 24h is bar 75 (close 137.5)
    assert ctx.move_24h_pct == pytest.approx(round((149.6 / 137.5 - 1) * 100, 3))


def test_no_look_ahead_into_the_forming_bar():
    closes = UP + [10_000.0]                       # bar 100 spans [100h, 101h): not closed at 100.5h
    ctx = entry_context(bars_from_closes(closes), "long", ENTRY + H // 2, 149.6)
    assert ctx.breakout is True and ctx.rsi_14 == 100.0


def test_stale_or_missing_bars_give_no_context_but_keep_hour():
    up = bars_from_closes(UP)
    ctx = entry_context(up, "long", ENTRY + 4 * H, 149.6)       # last bar ended 4h ago > 3h limit
    assert ctx.trend_aligned is None and ctx.breakout is None and ctx.rsi_14 is None
    assert ctx.hour_utc == 8                                    # 104h after Monday 00:00
    assert entry_context(None, "long", ENTRY, 1.0).trend_aligned is None


def test_short_history_gives_partial_context():
    ctx = entry_context(bars_from_closes(UP[:30]), "long", T0 + 30 * H, 115.0)
    assert ctx.trend_aligned is None and ctx.pullback is None    # EMA50 needs 55 bars
    assert ctx.breakout is not None and ctx.rsi_14 is not None


def test_hour_and_weekday():
    assert hour_utc(T0 + 13 * H + 5) == 13
    assert weekday(T0) == 0 and weekday(T0 + 6 * D) == 6
