"""Token-bucket limiter for the Hyperliquid /info + /exchange endpoints.

HL meters every request by a documented weight and enforces an aggregated
budget of ~1200/min per IP (hyperliquid.gitbook.io/hyperliquid-docs/
for-developers/api/rate-limits-and-user-limits, fetched 2026-10-02):

  weight 2:   l2Book, allMids, clearinghouseState, orderStatus,
              spotClearinghouseState, exchangeStatus
  weight 60:  userRole
  weight 20:  every other documented /info request -- meta, spotMeta,
              spotMetaAndAssetCtxs, metaAndAssetCtxs, perpDexs,
              delegatorSummary, userFillsByTime, candleSnapshot, ...
  +1 per 20 items returned: recentTrades, historicalOrders, userFills,
              userFillsByTime, fundingHistory, userFunding,
              nonUserFundingUpdates, twapHistory, userTwapSliceFills,
              userTwapSliceFillsByTime, delegatorHistory, delegatorRewards,
              validatorStats
  +1 per 60 items returned: candleSnapshot

A single copycat engine process is the only caller of this budget (no
fan-out across workers), so the bucket can use the whole documented budget.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Optional

_BASE_WEIGHT = {
    "l2Book": 2,
    "allMids": 2,
    "clearinghouseState": 2,
    "orderStatus": 2,
    "spotClearinghouseState": 2,
    "exchangeStatus": 2,
    "userRole": 60,
}
_DEFAULT_WEIGHT = 20

_PER_20_ITEMS = frozenset({
    "recentTrades", "historicalOrders", "userFills", "userFillsByTime",
    "fundingHistory", "userFunding", "nonUserFundingUpdates", "twapHistory",
    "userTwapSliceFills", "userTwapSliceFillsByTime", "delegatorHistory",
    "delegatorRewards", "validatorStats",
})


def endpoint_weight(req_type: Optional[str], item_count: Optional[int] = None) -> int:
    """Pre-call weight estimate for one /info `type`.

    `item_count`, when known ahead of the call (e.g. a capped page size for
    userFillsByTime, or an estimated candle count for candleSnapshot), adds
    the documented per-item surcharge. Omit it to charge just the base
    weight -- always safe to under-estimate since the limiter only exists
    to keep OUR pacing under the budget, not to bill exactly what HL bills.
    """
    base = _BASE_WEIGHT.get(req_type or "", _DEFAULT_WEIGHT)
    if item_count:
        if req_type == "candleSnapshot":
            return base + math.ceil(item_count / 60)
        if req_type in _PER_20_ITEMS:
            return base + math.ceil(item_count / 20)
    return base


class TokenBucket:
    """Thread-safe token bucket. `acquire(weight)` blocks (up to max_wait)
    until enough tokens have refilled, then deducts them. Returns False --
    never raises -- if the wait would exceed max_wait; the caller treats
    that as "skip this request" (the http layer returns None)."""

    def __init__(self, capacity: float, refill_per_sec: float):
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._refill = float(refill_per_sec)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, weight: int = 20, max_wait: float = 10.0) -> bool:
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._last) * self._refill,
                )
                self._last = now
                if self._tokens >= weight:
                    self._tokens -= weight
                    return True
                if self._refill <= 0:
                    return False  # no refill -- will never recover
                deficit = weight - self._tokens
                sleep_for = deficit / self._refill
            if time.monotonic() + sleep_for > deadline:
                return False
            time.sleep(min(sleep_for, 0.5))


# Env-tunable so tests (and anyone who wants a tighter local budget) don't
# have to monkeypatch internals. Defaults to the full documented budget:
# capacity 1200, refill 20/s (= 1200/min).
HL_LIMITER = TokenBucket(
    capacity=float(os.environ.get("COPYCAT_HL_RATE_CAPACITY", "1200")),
    refill_per_sec=float(os.environ.get("COPYCAT_HL_RATE_REFILL_PER_SEC", "20")),
)
