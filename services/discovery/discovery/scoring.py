"""Risk-adjusted score: ranks candidates by what copying them would have
earned a simulated copier, not by the leader's own PnL.

    raw = sim_return_pct / max(5, |sim_max_drawdown_pct|)

A return/drawdown ratio (bounded below at a 5% drawdown floor so a leader
who happened to have ~0% drawdown doesn't get a divide-by-near-zero score
blowup). Then two penalties, applied in this order:

    1. Any liquidation is a hard penalty: `raw -= LIQUIDATION_PENALTY` per
       liquidation. LIQUIDATION_PENALTY (50.0) is picked so that even a
       spectacular raw ratio (e.g. a 200%-return / 5%-floor-drawdown leader,
       raw=40) still lands negative after just one liquidation, and a
       leader who gets liquidated can never outrank a merely-steady one.
       This is the explicit requirement: a high-PnL leader whose copies
       get liquidated must rank below a steady one -- see
       tests/test_scoring.py::test_liquidation_outranked_by_steady_leader.
    2. Fewer than MIN_TRUSTED_COPIES (5) executed copies is a statistical
       trust problem, not a risk problem: too little data to believe the
       ratio means anything, win or lose. Flagged "too_few_trades" and the
       raw score is multiplied by TOO_FEW_TRADES_DISCOUNT (0.2) -- heavily
       discounted, not zeroed, so a small positive edge still outranks a
       small negative one at the same low trade count, but never outranks
       a well-sampled steady performer.

Flags accumulate (a leader can be both liquidated and too-few-trades).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

LIQUIDATION_PENALTY = 50.0
MIN_TRUSTED_COPIES = 5
TOO_FEW_TRADES_DISCOUNT = 0.2
DRAWDOWN_FLOOR_PCT = 5.0


@dataclass
class ScoreResult:
    score: float
    flags: List[str] = field(default_factory=list)


def score_candidate(sim_return_pct: float, sim_max_drawdown_pct: float,
                     sim_liquidations: int, sim_copies: int) -> ScoreResult:
    flags: List[str] = []
    raw = sim_return_pct / max(DRAWDOWN_FLOOR_PCT, abs(sim_max_drawdown_pct))

    if sim_liquidations > 0:
        flags.append("liquidated")
        raw -= LIQUIDATION_PENALTY * sim_liquidations

    if sim_copies < MIN_TRUSTED_COPIES:
        flags.append("too_few_trades")
        raw *= TOO_FEW_TRADES_DISCOUNT

    return ScoreResult(score=raw, flags=flags)
