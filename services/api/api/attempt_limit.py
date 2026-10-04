"""In-process attempt limiter for secret-bearing account routes (create, import,
sign-in submit, refresh-agent, transfer, import-env). Sliding windows per bucket:
at most PER_MINUTE attempts in 60 s and PER_HOUR in 3600 s, counted whether the
attempt succeeds or not, so passphrase guessing is slow on top of scrypt's cost.
One trader per install, so buckets are per route, not per client."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException

PER_MINUTE = 5
PER_HOUR = 30


class AttemptLimiter:
    def __init__(self, per_minute: int = PER_MINUTE, per_hour: int = PER_HOUR,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute, self.per_hour, self.clock = per_minute, per_hour, clock
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str) -> None:
        """Record one attempt or raise 429."""
        now = self.clock()
        with self._lock:
            hits = self._hits[bucket]
            while hits and now - hits[0] >= 3600:
                hits.popleft()
            last_min = sum(1 for t in hits if now - t < 60)
            if last_min >= self.per_minute or len(hits) >= self.per_hour:
                raise HTTPException(429, "too many attempts, wait a minute and try again")
            hits.append(now)
