"""Gate tests for hl.rate_limit: the token bucket's math and the documented
per-endpoint weight table. No network, no sleeping past a few ms.
"""
from __future__ import annotations

import time

from hl.rate_limit import TokenBucket, endpoint_weight

# ── endpoint_weight: matches the documented table ───────────────────────────

def test_weight_2_endpoints():
    for t in ("l2Book", "allMids", "clearinghouseState", "orderStatus",
              "spotClearinghouseState", "exchangeStatus"):
        assert endpoint_weight(t) == 2


def test_weight_60_userRole():
    assert endpoint_weight("userRole") == 60


def test_weight_20_default_for_unknown_or_undocumented():
    assert endpoint_weight("meta") == 20
    assert endpoint_weight("spotMetaAndAssetCtxs") == 20
    assert endpoint_weight("perpDexs") == 20
    assert endpoint_weight("delegatorSummary") == 20
    assert endpoint_weight("somethingHlAddsNextWeek") == 20
    assert endpoint_weight(None) == 20


def test_userFillsByTime_base_weight_is_20():
    assert endpoint_weight("userFillsByTime") == 20


def test_userFillsByTime_plus_per_20_items():
    # 2000 fills in one page -> +100 (2000 / 20)
    assert endpoint_weight("userFillsByTime", item_count=2000) == 120
    # a partial page still rounds UP to the next 20-item increment
    assert endpoint_weight("userFillsByTime", item_count=1) == 21
    assert endpoint_weight("userFillsByTime", item_count=21) == 22


def test_candleSnapshot_plus_per_60_items():
    assert endpoint_weight("candleSnapshot") == 20
    assert endpoint_weight("candleSnapshot", item_count=60) == 21
    assert endpoint_weight("candleSnapshot", item_count=61) == 22
    assert endpoint_weight("candleSnapshot", item_count=5000) == 20 + 84  # ceil(5000/60) == 84


def test_item_count_ignored_for_non_per_item_endpoints():
    # clearinghouseState has no per-item surcharge regardless of item_count
    assert endpoint_weight("clearinghouseState", item_count=99999) == 2


# ── TokenBucket ──────────────────────────────────────────────────────────────

def test_bucket_allows_up_to_capacity_instantly():
    b = TokenBucket(capacity=100, refill_per_sec=0)
    assert b.acquire(40, max_wait=1) is True
    assert b.acquire(60, max_wait=1) is True
    # exhausted, no refill -> next acquire must fail fast, not hang
    start = time.monotonic()
    assert b.acquire(1, max_wait=0.2) is False
    assert time.monotonic() - start < 1.0


def test_bucket_refills_over_time():
    b = TokenBucket(capacity=10, refill_per_sec=100)  # 10 tokens back in 0.1s
    assert b.acquire(10, max_wait=1) is True
    assert b.acquire(10, max_wait=1) is True  # waits ~0.1s for refill, then succeeds


def test_bucket_never_exceeds_capacity():
    b = TokenBucket(capacity=10, refill_per_sec=1000)
    assert b.acquire(10, max_wait=1) is True
    time.sleep(0.05)
    with b._lock:
        b._tokens = min(b._capacity, b._tokens + 0.05 * b._refill)
    assert b._tokens <= 10.0001


def test_bucket_times_out_without_raising():
    b = TokenBucket(capacity=1, refill_per_sec=0.001)
    assert b.acquire(1, max_wait=1) is True  # drains the only token
    assert b.acquire(1, max_wait=0.05) is False  # would need ~1000s to refill


def test_token_bucket_drain_empties():
    b = TokenBucket(capacity=10, refill_per_sec=0)
    b.drain()
    assert b.acquire(1, max_wait=0.01) is False


# ── SharedTokenBucket: one budget across processes, engine priority ─────────

import os
import subprocess
import sys
from pathlib import Path

import pytest
from hl import rate_limit
from hl.rate_limit import SharedTokenBucket


def _shared(path, priority="engine", capacity=100, refill=0.0, reserve=0.4):
    return SharedTokenBucket(path, capacity=capacity, refill_per_sec=refill,
                             priority=priority, reserve_frac=reserve)


def test_two_buckets_on_one_file_share_the_budget(tmp_path):
    """Two instances = two open file descriptions, so flock really
    serializes them exactly as it would two processes."""
    path = tmp_path / "hl_rate.bucket"
    a, b = _shared(path), _shared(path)
    assert a.acquire(70, max_wait=0) is True
    assert b.acquire(40, max_wait=0) is False     # only 30 left, shared
    assert b.acquire(30, max_wait=0) is True
    assert a.tokens() == pytest.approx(0.0, abs=1e-6)


def test_background_keeps_a_40pct_reserve_for_the_engine(tmp_path):
    path = tmp_path / "hl_rate.bucket"
    bg, eng = _shared(path, "background"), _shared(path, "engine")
    assert bg.acquire(60, max_wait=0) is True      # 100 -> 40, exactly the reserve
    assert bg.acquire(1, max_wait=0.05) is False   # would dip into the reserve: refused
    assert eng.acquire(40, max_wait=0) is True     # engine gets the whole reserve


def test_background_sleeps_until_refill_clears_the_reserve(tmp_path):
    path = tmp_path / "hl_rate.bucket"
    bg = _shared(path, "background", capacity=100, refill=1000.0)
    eng = _shared(path, "engine", capacity=100, refill=1000.0)
    assert eng.acquire(100, max_wait=0) is True     # drained by the engine
    assert bg.acquire(10, max_wait=1.0) is True     # waits ~50ms for 50 tokens, then proceeds


def test_background_weight_larger_than_usable_budget_fails_fast(tmp_path):
    bg = _shared(tmp_path / "b", "background", capacity=100, refill=1000.0)
    assert bg.acquire(61, max_wait=5.0) is False    # 61 + 40 reserve > capacity: never satisfiable


def test_shared_drain_is_seen_by_the_other_instance(tmp_path):
    path = tmp_path / "hl_rate.bucket"
    a, b = _shared(path), _shared(path)
    a.drain()
    assert b.acquire(1, max_wait=0) is False


def test_corrupt_file_is_treated_as_full(tmp_path):
    path = tmp_path / "hl_rate.bucket"
    path.write_text("garbage nan")
    assert _shared(path).acquire(100, max_wait=0) is True


def test_unusable_path_falls_back_to_in_process_bucket(tmp_path, caplog):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")                         # a FILE where the data dir should be
    b = _shared(blocker / "hl_rate.bucket")
    assert b.acquire(10, max_wait=0) is True        # still paces, privately
    assert b._fallback is not None
    assert "falling back" in caplog.text
    assert b.acquire(91, max_wait=0) is False       # fallback honors capacity too


def test_real_second_process_shares_the_bucket(tmp_path):
    """The actual cross-process case: a child Python process drains the
    file; this process then sees the drained budget."""
    path = tmp_path / "hl_rate.bucket"
    hl_pkg = Path(rate_limit.__file__).parent
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import rate_limit as r; "
        "b = r.SharedTokenBucket(sys.argv[2], capacity=100, refill_per_sec=0); "
        "print(b.acquire(95, max_wait=0))"
    )
    out = subprocess.run([sys.executable, "-c", code, str(hl_pkg), str(path)],
                         capture_output=True, text=True, timeout=10, check=False)
    assert out.stdout.strip() == "True", out.stderr
    mine = _shared(path)
    assert mine.acquire(10, max_wait=0) is False
    assert mine.acquire(5, max_wait=0) is True


def test_priority_env(monkeypatch):
    monkeypatch.delenv("COPYCAT_HL_PRIORITY", raising=False)
    assert rate_limit.priority() == "engine"
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "Background")
    assert rate_limit.priority() == "background"
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "nonsense")
    assert rate_limit.priority() == "engine"


def test_default_limiter_is_shared_file_in_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "background")
    lim = rate_limit.build_default_limiter()
    assert isinstance(lim, SharedTokenBucket)
    assert lim.path == tmp_path / "hl_rate.bucket"
    assert lim.priority == "background"
    assert not lim.path.exists()                    # no file until first acquire
    assert lim.acquire(2, max_wait=0) is True
    assert lim.path.exists()


def test_set_priority_rebuilds_the_module_limiter(monkeypatch, tmp_path):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rate_limit, "HL_LIMITER", rate_limit.HL_LIMITER)   # restored after test
    monkeypatch.setenv("COPYCAT_HL_PRIORITY", "engine")
    rate_limit.set_priority("background")
    assert rate_limit.HL_LIMITER.priority == "background"
    assert os.environ["COPYCAT_HL_PRIORITY"] == "background"
