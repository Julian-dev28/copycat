"""Copy Fit (spec section 3): weights, percentiles, parts, gates and caps."""
from __future__ import annotations

import pytest
from discovery.scout import copy_fit as F

DAY = 86_400_000
NOW = 1_790_000_000_000


def mk(a, **kw):
    base = dict(address=a, account_value_usd=50_000.0, sim_score=10.0, sharpe_30d=1.0, max_drawdown_30d_pct=5.0,
                profitable_days_pct_30d=60.0, win_rate_30d_pct=55.0, trips_30d=50, copy_capacity_pct=100.0,
                last_fill_ms=NOW - 3_600_000, sim_liquidations=0, sim_copies=20, flags=[])
    base.update(kw)
    return F.FitInput(**base)


def test_weights_sum_to_one_and_match_spec():
    assert sum(F.WEIGHTS.values()) == pytest.approx(1.0)
    assert F.WEIGHTS["sim"] == 0.40 and F.WEIGHTS["sharpe"] == 0.15


def test_percentile_ranks_ties_and_nulls():
    assert F.percentile_ranks([1.0, 2.0, 2.0, 3.0, None]) == [0.0, 0.5, 0.5, 1.0, 0.0]
    assert F.percentile_ranks([7.0, None]) == [0.5, 0.0]


def test_sample_and_recency_parts():
    assert F.sample_part(0) == 0 and F.sample_part(50) == 1.0 and F.sample_part(500) == 1.0
    assert F.sample_part(9) == pytest.approx(1 / 1.70757, abs=1e-4)       # log10(10)/log10(51)
    assert F.recency_part(NOW - DAY, NOW) == 1.0
    assert F.recency_part(NOW - 4 * DAY, NOW) == pytest.approx(0.5)
    assert F.recency_part(NOW - 7 * DAY, NOW) == 0.0 and F.recency_part(None, NOW) == 0.0


def test_best_in_every_part_scores_100_and_blend_is_weighted():
    out = F.compute([mk("a", sim_score=1, sharpe_30d=0, max_drawdown_30d_pct=9, profitable_days_pct_30d=1,
                        win_rate_30d_pct=1), mk("b")], NOW)
    assert out["b"].value == 100.0 and out["b"].caps == [] and out["b"].cohort_size == 2
    # a: every percentile part 0; sample 1, capacity 1, recency 1 -> 0.10 + 0.05 + 0.05
    assert out["a"].value == pytest.approx(20.0)


def test_gates_and_caps_in_order():
    cohort = [mk("ok"), mk("small", account_value_usd=999.0), mk("idle", last_fill_ms=NOW - 8 * DAY),
              mk("liq", sim_liquidations=1), mk("few", sim_copies=4), mk("hft", flags=["hft"]),
              mk("vault", flags=["vault"]), mk("trunc", flags=["fills_truncated"]),
              mk("both", sim_liquidations=2, sim_copies=1)]
    out = F.compute(cohort, NOW)
    assert out["small"].value == 0 and "inactive" in out["small"].caps
    assert out["idle"].value == 0 and "inactive" in out["idle"].caps
    assert out["liq"].value <= 20 and out["liq"].caps == ["liquidated"]
    assert out["few"].value <= 40 and out["few"].caps == ["too_few_trades"]
    assert out["hft"].value <= 50 and out["vault"].value <= 50
    assert out["trunc"].value == out["ok"].value and out["trunc"].caps == ["fills_truncated"]
    assert out["both"].caps == ["liquidated", "too_few_trades"] and out["both"].value <= 20


def test_steady_outranks_higher_pnl_liquidated():
    out = F.compute([mk("steady", sim_score=5.0), mk("wild", sim_score=90.0, sharpe_30d=4.0, sim_liquidations=1)], NOW)
    assert out["steady"].value > out["wild"].value


def test_deterministic_for_fixed_cohort():
    cohort = [mk(f"w{i}", sim_score=float(i % 3), sharpe_30d=float(i)) for i in range(20)]
    assert F.compute(cohort, NOW) == F.compute(list(cohort), NOW)
