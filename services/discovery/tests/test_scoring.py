from __future__ import annotations

import pytest

from discovery.scoring import UNSCORED, score_candidate


def test_steady_leader_scores_return_over_drawdown():
    r = score_candidate(20.0, -10.0, 0, 10)
    assert r.score == pytest.approx(2.0) and r.flags == []


def test_drawdown_floor_prevents_blowup():
    assert score_candidate(20.0, -0.01, 0, 10).score == pytest.approx(4.0)


def test_liquidated_high_pnl_leader_ranks_below_steady_leader():
    steady = score_candidate(20.0, -10.0, 0, 10)
    liq = score_candidate(200.0, -50.0, 1, 8)
    assert "liquidated" in liq.flags and liq.score < steady.score < 100


def test_trusted_scores_are_clamped():
    assert score_candidate(10_000.0, -1.0, 0, 50).score == 100.0
    assert score_candidate(-100.0, -100.0, 5, 50).score == -100.0


def test_too_few_trades_never_outranks_any_real_copier():
    """Regression (coordinator bug 4): 0xbf732ea0, +79% / 11 copies / 1 liq /
    DD -34% scored -47.68 and ranked BELOW two wallets with 0 copies at 0.00."""
    real = score_candidate(79.0, -34.0, 1, 11)
    worst_real = score_candidate(-99.0, -99.0, 10, 11)
    zero = score_candidate(0.0, 0.0, 0, 0)
    best_tiny = score_candidate(500.0, -1.0, 0, 4)
    assert "too_few_trades" in zero.flags and "too_few_trades" in best_tiny.flags
    assert min(real.score, worst_real.score) > max(zero.score, best_tiny.score)
    assert best_tiny.score > zero.score          # ordering inside the band survives


def test_no_sentinel_scores():
    """Regression (coordinator bug 3): -1e9 leaked into the table."""
    zero = score_candidate(0.0, 0.0, 0, 0)
    assert zero.score == UNSCORED == -200.0
    assert -201.0 <= score_candidate(-1e6, -100.0, 3, 2).score <= -199.0
