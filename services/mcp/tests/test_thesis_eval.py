"""Gate test for the deterministic half of evals/thesis_eval.py: the rubric
shape and the JSON-parsing / pass-fail math. No network, no Claude call --
that's thesis_eval.sh's job (periodic lane)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
from thesis_eval import (  # noqa: E402
    MAX_PER_CRITERION,
    MAX_TOTAL,
    PASS_TOTAL,
    RUBRIC,
    extract_json,
    passes,
    score_result,
)


def test_rubric_matches_the_research_doc_shape():
    assert len(RUBRIC) == 12
    assert [c.num for c in RUBRIC] == list(range(1, 13))
    assert MAX_PER_CRITERION == 2 and MAX_TOTAL == 24 and PASS_TOTAL == 18
    # every criterion documents what earns a 2, not just a name
    assert all(len(c.bar_for_2) > 10 for c in RUBRIC)


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('{"scores": {"1": 2}}') == {"scores": {"1": 2}}
    assert extract_json('```json\n{"scores": {"1": 2}}\n```') == {"scores": {"1": 2}}
    assert extract_json('Sure, here you go:\n{"scores": {"1": 2}}\nhope that helps') == {"scores": {"1": 2}}
    assert extract_json("not json at all") is None


def _scores(**kw):
    s = {str(i): 2 for i in range(1, 13)}
    s.update({k: v for k, v in kw.items()})
    return {"scores": s}


def test_score_result_sums_and_passes_threshold():
    total, per, problems = score_result(_scores())
    assert total == 24 and problems == [] and passes(total, per)


def test_a_single_zero_disqualifies_even_at_a_high_total():
    total, per, problems = score_result(_scores(**{"10": 0}))
    assert total == 22                      # well above PASS_TOTAL
    assert not passes(total, per)           # but one 0 disqualifies regardless


def test_missing_or_out_of_range_criterion_counts_as_zero_not_dropped():
    s = _scores()
    del s["scores"]["7"]
    total, per, problems = score_result(s)
    assert per[7] == 0 and any("7" in p for p in problems)
    assert not passes(total, per)

    s2 = _scores(**{"3": 5})   # out of range
    total2, per2, problems2 = score_result(s2)
    assert per2[3] == MAX_PER_CRITERION and any("3" in p for p in problems2)


def test_exactly_at_the_pass_bar_with_no_zeros_passes():
    # 18 = 12 criteria averaging 1.5; spread six 1s and six 2s.
    s = _scores(**{str(i): 1 for i in range(1, 7)})
    total, per, _ = score_result(s)
    assert total == 18 and passes(total, per)
    total2, per2, _ = score_result(_scores(**{str(i): 1 for i in range(1, 8)}))
    assert total2 == 17 and not passes(total2, per2)
