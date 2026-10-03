"""Risk-adjusted score: ranks candidates by what copying them would have
earned a simulated copier, not by the leader's own PnL.

    raw = sim_return_pct / max(5, |sim_max_drawdown_pct|) - 50 * liquidations

Return over drawdown, with a 5% drawdown floor so ~0% drawdown can't blow
the ratio up. Each liquidation subtracts LIQUIDATION_PENALTY (50): with
fixed-margin sizing one liquidation costs only ~1% of equity, so without
the penalty a leader whose moves wipe out max-leverage copies could rank
above a steady one. 50 makes even a 40x raw ratio go negative after one.

Two bands, so a tiny sample can never outrank a real track record:

    trusted (>= MIN_TRUSTED_COPIES copies):  score = clamp(raw, -100, 100)
    too_few_trades (fewer, incl. 0):         score = -200 + clamp(raw, -100, 100) / 100
                                             i.e. in [-201, -199]; 0 copies -> -200

Every trusted wallet (>= -100) outranks every too_few_trades wallet
(<= -199), and the band keeps the tiny-sample ordering among themselves.
A wallet we could not simulate at all (fills read failed, HFT skipped,
no perp trades) gets -200 plus a flag that says why. No sentinels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

LIQUIDATION_PENALTY = 50.0
MIN_TRUSTED_COPIES = 5
DRAWDOWN_FLOOR_PCT = 5.0
SCORE_CAP = 100.0
TOO_FEW_BASE = -200.0
UNSCORED = TOO_FEW_BASE


@dataclass
class ScoreResult:
    score: float
    flags: List[str] = field(default_factory=list)


def _clamp(x: float) -> float:
    return max(-SCORE_CAP, min(SCORE_CAP, x))


def score_candidate(sim_return_pct: float, sim_max_drawdown_pct: float,
                    sim_liquidations: int, sim_copies: int) -> ScoreResult:
    flags: List[str] = []
    raw = sim_return_pct / max(DRAWDOWN_FLOOR_PCT, abs(sim_max_drawdown_pct))
    if sim_liquidations > 0:
        flags.append("liquidated")
        raw -= LIQUIDATION_PENALTY * sim_liquidations
    if sim_copies < MIN_TRUSTED_COPIES:
        flags.append("too_few_trades")
        return ScoreResult(score=TOO_FEW_BASE + _clamp(raw) / SCORE_CAP, flags=flags)
    return ScoreResult(score=_clamp(raw), flags=flags)
