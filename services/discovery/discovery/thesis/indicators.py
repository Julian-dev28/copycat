"""Pure indicator math on 1h bars and the per-entry market context.

Look-ahead rule: an entry at time T only sees bars that CLOSED at or
before T (bar start + 1h <= T). The bar the trader entered inside is
never used, so the context is what the trader could have seen.

Each entry is computed from its own slice of the last WARMUP_BARS closed
bars, so one trip's context never depends on which other trips exist.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from contracts.models import EntryContext

from . import config as C


@dataclass(frozen=True)
class Bars:
    """One coin's 1h bars, sorted by start time."""
    t: List[int]
    h: List[float]
    l: List[float]
    c: List[float]

    @staticmethod
    def from_rows(rows: Sequence[Dict[str, float]]) -> "Bars":
        rs = sorted(rows, key=lambda r: int(r["t_ms"]))
        return Bars([int(r["t_ms"]) for r in rs], [float(r["h"]) for r in rs],
                    [float(r["l"]) for r in rs], [float(r["c"]) for r in rs])

    def __len__(self) -> int:
        return len(self.t)


def ema(values: Sequence[float], period: int) -> List[float]:
    """EMA seeded with the SMA of the first `period` values; the returned
    list starts at that seed (len = len(values) - period + 1). Empty when
    there are fewer than `period` values."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: Sequence[float], period: int = C.RSI_PERIOD) -> Optional[float]:
    """Wilder RSI of the last close. Needs period + 1 closes. 100 when there
    were no losses, 50 when the series is flat."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for g, lo in zip(gains[period:], losses[period:]):
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + lo) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _last_closed(bars: Bars, at_ms: int) -> int:
    """Index of the last bar with start + step <= at_ms, or -1."""
    return bisect.bisect_right(bars.t, at_ms - C.CANDLE_STEP_MS) - 1


def _fresh(bars: Bars, i: int, at_ms: int) -> bool:
    return i >= 0 and at_ms - (bars.t[i] + C.CANDLE_STEP_MS) <= C.MAX_BAR_STALENESS_MS


def hour_utc(t_ms: int) -> int:
    return (t_ms // C.HOUR_MS) % 24


def weekday(t_ms: int) -> int:
    """0 = Monday. Epoch day 0 (1970-01-01) was a Thursday."""
    return (t_ms // C.DAY_MS + 3) % 7


def entry_context(bars: Optional[Bars], side: str, entry_ms: int, entry_px: float) -> EntryContext:
    """Market state at one entry. Every field the bars cannot support is None."""
    ctx = EntryContext(hour_utc=hour_utc(entry_ms))
    if bars is None or len(bars) == 0 or entry_px <= 0:
        return ctx
    i = _last_closed(bars, entry_ms)
    if not _fresh(bars, i, entry_ms):
        return ctx
    lo = max(0, i - C.WARMUP_BARS + 1)
    closes = bars.c[lo:i + 1]
    is_long = side == "long"

    e = ema(closes, C.EMA_PERIOD)
    ema_now: Optional[float] = None
    if len(e) > C.EMA_SLOPE_BARS:
        ema_now = e[-1]
        slope = e[-1] - e[-1 - C.EMA_SLOPE_BARS]
        ctx.trend_aligned = (slope > 0) if is_long else (slope < 0)

    if i + 1 >= C.RANGE_BARS:
        hi20 = max(bars.h[i - C.RANGE_BARS + 1:i + 1])
        lo20 = min(bars.l[i - C.RANGE_BARS + 1:i + 1])
        tol = C.BREAKOUT_TOL_PCT / 100.0
        pb = C.PULLBACK_MIN_PCT / 100.0
        if is_long:
            ctx.breakout = entry_px >= hi20 * (1 - tol)
            if ema_now is not None:
                ctx.pullback = entry_px <= hi20 * (1 - pb) and entry_px > ema_now
        else:
            ctx.breakout = entry_px <= lo20 * (1 + tol)
            if ema_now is not None:
                ctx.pullback = entry_px >= lo20 * (1 + pb) and entry_px < ema_now

    r = rsi(closes)
    ctx.rsi_14 = round(r, 2) if r is not None else None

    j = _last_closed(bars, entry_ms - C.DAY_MS)
    if _fresh(bars, j, entry_ms - C.DAY_MS) and bars.c[j] > 0:
        ctx.move_24h_pct = round((entry_px / bars.c[j] - 1.0) * 100.0, 3)
    return ctx
