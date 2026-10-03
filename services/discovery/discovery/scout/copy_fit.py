"""Copy Fit (spec section 3): a 0..100 blend of cohort percentiles with the
copy-sim as the dominant term, then gates and caps. Pure: no I/O, no clock
(now_ms is an argument), deterministic for a fixed cohort.

    pct(x) = percentile rank within the cohort, 0..1, ties averaged, nulls -> 0
             (less + (equal - 1) / 2) / (n - 1) over the n non-null values;
             a single non-null value gets 0.5
    fit    = 100 * sum(weight * part)

Gates and caps, after the blend, in this order (each adds its flag to caps):
    account value < $1,000 or no fill in 7 d   fit = 0          inactive
    sim liquidations > 0                       fit <= 20        liquidated
    sim copies < 5                             fit <= 40        too_few_trades
    style algo (hft)                           fit <= 50        hft
    vault                                      fit <= 50        vault
    fills truncated                            no cap           fills_truncated (warning only)
A cap's flag is listed whenever its condition holds, even when the blend
was already under the cap: the page explains the ceiling either way.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from contracts.models import CopyFit

DAY_MS = 86_400_000

WEIGHTS: Dict[str, float] = {
    "sim": 0.40,
    "sharpe": 0.15,
    "drawdown": 0.10,
    "consistency": 0.10,
    "win_rate": 0.05,
    "sample": 0.10,
    "capacity": 0.05,
    "recency": 0.05,
}

INACTIVE_MIN_AV = 1_000.0
INACTIVE_DAYS = 7
SAMPLE_FULL_TRIPS = 50
CAP_LIQUIDATED = 20.0
CAP_TOO_FEW = 40.0
MIN_COPIES = 5
CAP_HFT = 50.0
CAP_VAULT = 50.0


@dataclass
class FitInput:
    address: str
    account_value_usd: float
    sim_score: Optional[float]           # scoring.score_candidate output; None = not simulated
    sharpe_30d: Optional[float]
    max_drawdown_30d_pct: Optional[float]   # >= 0
    profitable_days_pct_30d: Optional[float]
    win_rate_30d_pct: Optional[float]
    trips_30d: int
    copy_capacity_pct: Optional[float]   # 0..100
    last_fill_ms: Optional[int]
    sim_liquidations: int = 0
    sim_copies: int = 0
    flags: List[str] = field(default_factory=list)   # hft / vault / fills_truncated / algo


def percentile_ranks(values: Sequence[Optional[float]]) -> List[float]:
    """pct(x) for every entry; None -> 0.0."""
    present = sorted(v for v in values if v is not None)
    n = len(present)
    out: List[float] = []
    for v in values:
        if v is None:
            out.append(0.0)
            continue
        if n == 1:
            out.append(0.5)
            continue
        less = _count_lt(present, v)
        equal = _count_le(present, v) - less
        out.append((less + (equal - 1) / 2.0) / (n - 1))
    return out


def _count_lt(sorted_vals: Sequence[float], v: float) -> int:
    return bisect.bisect_left(sorted_vals, v)


def _count_le(sorted_vals: Sequence[float], v: float) -> int:
    return bisect.bisect_right(sorted_vals, v)


def sample_part(trips: int) -> float:
    return min(1.0, math.log10(1 + max(0, trips)) / math.log10(1 + SAMPLE_FULL_TRIPS))


def recency_part(last_fill_ms: Optional[int], now_ms: int) -> float:
    """1 within 24 h, linear to 0 at 7 d."""
    if last_fill_ms is None:
        return 0.0
    age = now_ms - last_fill_ms
    if age <= DAY_MS:
        return 1.0
    return max(0.0, 1.0 - (age - DAY_MS) / (6 * DAY_MS))


def compute(cohort: Sequence[FitInput], now_ms: int) -> Dict[str, CopyFit]:
    n = len(cohort)
    sim = percentile_ranks([c.sim_score for c in cohort])
    shp = percentile_ranks([c.sharpe_30d for c in cohort])
    ddn = percentile_ranks([None if c.max_drawdown_30d_pct is None else -c.max_drawdown_30d_pct for c in cohort])
    con = percentile_ranks([c.profitable_days_pct_30d for c in cohort])
    win = percentile_ranks([c.win_rate_30d_pct for c in cohort])
    out: Dict[str, CopyFit] = {}
    for i, c in enumerate(cohort):
        parts = {
            "sim": sim[i], "sharpe": shp[i], "drawdown": ddn[i], "consistency": con[i], "win_rate": win[i],
            "sample": sample_part(c.trips_30d),
            "capacity": 0.0 if c.copy_capacity_pct is None else max(0.0, min(1.0, c.copy_capacity_pct / 100.0)),
            "recency": recency_part(c.last_fill_ms, now_ms),
        }
        fit = 100.0 * sum(WEIGHTS[k] * v for k, v in parts.items())
        caps: List[str] = []
        stale = c.last_fill_ms is None or now_ms - c.last_fill_ms > INACTIVE_DAYS * DAY_MS
        if c.account_value_usd < INACTIVE_MIN_AV or stale:
            fit = 0.0
            caps.append("inactive")
        if c.sim_liquidations > 0:
            fit = min(fit, CAP_LIQUIDATED)
            caps.append("liquidated")
        if c.sim_copies < MIN_COPIES:
            fit = min(fit, CAP_TOO_FEW)
            caps.append("too_few_trades")
        if "hft" in c.flags or "algo" in c.flags:
            fit = min(fit, CAP_HFT)
            caps.append("hft")
        if "vault" in c.flags:
            fit = min(fit, CAP_VAULT)
            caps.append("vault")
        if "fills_truncated" in c.flags:
            caps.append("fills_truncated")
        out[c.address] = CopyFit(value=round(fit, 2), parts={k: round(v, 6) for k, v in parts.items()},
                                 weights=dict(WEIGHTS), caps=caps, cohort_size=n)
    return out
