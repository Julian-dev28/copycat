"""The budget eval's pure helpers (evals/stats_budget_check.py): the failure
and bucket give-up extraction from a pass's log, the warm-path judgement of
check 3, and the ETA honesty-gate evidence. The eval itself reads real
Hyperliquid; these keep its reading of a pass deterministic."""
from __future__ import annotations

import importlib.util
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "evals" / "stats_budget_check.py"
spec = importlib.util.spec_from_file_location("stats_budget_check", EVAL)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)   # argv-free at import: main() parses sys.argv

LOG = """\
2026-10-15 08:10:25,161 WARNING hl.http: [hl.http] rate budget exhausted for portfolio (weight=20, waited 30s) -- returning None
2026-10-15 08:10:25,161 ERROR hl.venue: [hl.venue] portfolio: read failed or bad shape for user=0x3440f23a87f1950e7a88cd248fd270e92d1132c5: NoneType
2026-10-15 08:10:25,162 WARNING discovery.scout.stats: scout stage B: 0x3440f23a87f1950e7a88cd248fd270e92d1132c5 failed (1 in a row): portfolio read failed
2026-10-15 08:14:25,928 WARNING hl.http: [hl.http] rate budget exhausted for userFillsByTime (weight=20, waited 30s) -- returning None
2026-10-15 08:19:24,522 WARNING hl.http: [hl.http] rate budget exhausted for userFillsByTime (weight=20, waited 30s) -- returning None
2026-10-15 08:19:24,522 WARNING discovery.scout.stats: scout stage B: 0x3a23b10845e911b6944d9dc2f1f480fca3af35d6 failed (1 in a row): fills read failed for 0x3a23b10845e911b6944d9dc2f1f480fca3af35d6 [1791982935661, 1792023531274]
2026-10-15 08:25:13,051 WARNING discovery.scout.stats: scout stage B: 0xcf5343ba750a6e30afbb1dadda08bc78f8c8ee11 funding read failed, netting 0: funding read failed for 0xcf5343ba750a6e30afbb1dadda08bc78f8c8ee11 [1, 2]
{
  "refresh_id": "abc",
  "stats_done": 16
}
"""


def test_failure_lines_list_each_failed_wallet_and_count_bucket_give_ups_per_read_type():
    failed, exhausted = ev.failure_lines(LOG)
    assert failed == [
        "0x3440f23a87f1950e7a88cd248fd270e92d1132c5: portfolio read failed",
        "0x3a23b10845e911b6944d9dc2f1f480fca3af35d6: fills read failed for 0x3a23b10845e911b6944d9dc2f1f480fca3af35d6 "
        "[1791982935661, 1792023531274]",
    ]   # the funding "netting 0" line is a degraded build, not a failed wallet
    assert exhausted == {"portfolio": 1, "userFillsByTime": 2}
    assert ev.failure_lines("") == ([], {})


def test_warm_path_check_judges_the_warm_path_not_the_all_wallet_median():
    # the 2026-10-15 07:35 warm pass: 11/20 on the full set, all-wallet p50 117, warm path about 40
    s = {"n": 20, "full_count": 11, "failed": 0, "weight_p50": 117.0, "warm_weight_p50": 40.0, "full_weight_p50": 393.0}
    ok, detail = ev.warm_path_check(s)        # no "built" key: an older summary counts every wallet as built
    assert ok and detail.startswith("warm path p50 40 over 9 wallet(s)") and "full set on 11/20 built (p50 393.0)" in detail
    ok, detail = ev.warm_path_check({**s, "warm_weight_p50": 61.0})
    assert not ok
    # every wallet took the full set: no warm path ran, the all-wallet median is judged and fails
    ok, detail = ev.warm_path_check({"n": 3, "full_count": 3, "weight_p50": 300.0, "warm_weight_p50": None})
    assert not ok and "every wallet took the full set" in detail
    # a summary written by a scout from before the field
    ok, detail = ev.warm_path_check({"n": 3, "full_count": 1, "weight_p50": 41.0})
    assert ok and "older summary" in detail
    assert ev.warm_path_check(None) == (False, "no summary")


def test_cheaper_check_compares_a_warm_path_build_with_a_cold_build():
    # the 2026-10-15 09:40 run: all-wallet medians cold 258.5 < warm 412.5 (8 cold builds failed, rebuilt warm)
    cold = {"n": 20, "built": 12, "full_count": 12, "failed": 8, "weight_p50": 242.5, "warm_weight_p50": None}
    warm = {"n": 20, "built": 19, "full_count": 11, "failed": 1, "weight_p50": 412.5, "warm_weight_p50": 40.0}
    ok, detail = ev.cheaper_check(cold, warm)
    assert ok and detail.startswith("cold build p50 242.5 over 12 built vs warm path p50 40.0")
    assert not ev.cheaper_check(cold, {**warm, "warm_weight_p50": 242.5})[0]
    assert not ev.cheaper_check(cold, {**warm, "warm_weight_p50": None})[0]      # no warm path: 412.5 vs 242.5 fails
    assert ev.cheaper_check(None, warm) == (False, "no summary")
    s = {"n": 20, "built": 19, "full_count": 11, "failed": 1, "weight_p50": 412.5, "warm_weight_p50": 40.0,
         "full_weight_p50": 695.0}
    assert ev.warm_path_check(s)[1].startswith("warm path p50 40 over 8 wallet(s); full set on 11/19 built")


def test_eta_gate_evidence_mirrors_the_honesty_gate():
    # hidden while done < 10 OR done < 10% of total; both must hold for the ETA to show
    samples = [(1, 40, None), (5, 40, None), (9, 40, None), (10, 40, 120.0), (20, 40, 60.0)]
    assert ev.eta_gate_evidence(samples) == (True, True)
    assert ev.eta_gate_evidence([(10, 200, None), (19, 200, None)]) == (True, False)   # 10 done but under 10%
    assert ev.eta_gate_evidence([]) == (False, False)
