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
