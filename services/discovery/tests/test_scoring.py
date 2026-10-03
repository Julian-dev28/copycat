from __future__ import annotations

import pytest

from discovery.scoring import score_candidate


def test_steady_leader_scores_return_over_drawdown():
    r = score_candidate(sim_return_pct=20.0, sim_max_drawdown_pct=-10.0, sim_liquidations=0, sim_copies=10)
    assert r.score == pytest.approx(2.0)
    assert r.flags == []


def test_drawdown_floor_prevents_blowup_near_zero_drawdown():
    r = score_candidate(sim_return_pct=20.0, sim_max_drawdown_pct=-0.01, sim_liquidations=0, sim_copies=10)
    assert r.score == pytest.approx(20.0 / 5.0)   # floor at 5%, not /0.01


def test_liquidated_high_pnl_leader_ranks_below_steady_leader():
    steady = score_candidate(sim_return_pct=20.0, sim_max_drawdown_pct=-10.0, sim_liquidations=0, sim_copies=10)
    liquidated = score_candidate(sim_return_pct=200.0, sim_max_drawdown_pct=-50.0, sim_liquidations=1, sim_copies=8)
    assert "liquidated" in liquidated.flags
    assert liquidated.score < steady.score
    assert liquidated.score < 0   # the penalty must overwhelm even a spectacular raw ratio


def test_too_few_trades_heavily_discounted_but_not_zeroed():
    r = score_candidate(sim_return_pct=50.0, sim_max_drawdown_pct=-5.0, sim_liquidations=0, sim_copies=3)
    assert "too_few_trades" in r.flags
    assert r.score == pytest.approx((50.0 / 5.0) * 0.2)


def test_too_few_trades_and_liquidated_both_flag_and_both_penalize():
    r = score_candidate(sim_return_pct=100.0, sim_max_drawdown_pct=-20.0, sim_liquidations=1, sim_copies=2)
    assert set(r.flags) == {"liquidated", "too_few_trades"}
    expected = ((100.0 / 20.0) - 50.0) * 0.2
    assert r.score == pytest.approx(expected)
