"""Queue for slow fingerprint computes. One worker thread per api process
runs one fingerprint at a time (spec 7.3's "rate-limited to 1 concurrent"
for on-demand builds); the work itself happens in a child process
(api.thesis_client.RealThesisClient), so the worker only waits on a pipe.

GET .../fingerprint semantics, per (address, window_days):
  - fresh result cached (< ttl)       -> the fingerprint (200)
  - stale result cached               -> the stale fingerprint (200, its
                                         `as_of_ms` says how old) and a
                                         refresh is queued behind it
  - nothing cached, queued or running -> ScoutStatus (202), poll again
  - last compute failed               -> that error once (route: 502/503),
                                         then forgotten so the next GET retries
  - queue full (max_pending)          -> QueueFull (route: 429)

State is in memory: an api restart drops the cache and the queue, which
only costs a recompute. Tests build it with autostart=False and run queued
jobs deterministically with drain().
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Callable, Deque, Dict, Optional, Tuple, Union

from contracts.models import ScoutStatus, StrategyFingerprint

logger = logging.getLogger(__name__)

Key = Tuple[str, int]


class QueueFull(RuntimeError):
    pass


class FingerprintJobs:
    def __init__(self, ttl_s: float = 900.0, max_pending: int = 16, autostart: bool = True,
                 clock: Callable[[], float] = time.time, max_cached: int = 512):
        self.ttl_s = ttl_s
        self.max_cached = max_cached
        self.max_pending = max_pending
        self.autostart = autostart
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: Dict[Key, Tuple[StrategyFingerprint, float]] = {}
        self._failed: Dict[Key, BaseException] = {}
        self._pending: Deque[Key] = collections.deque()
        self._clients: Dict[Key, Any] = {}
        self._running: Optional[Key] = None
        self._thread: Optional[threading.Thread] = None

    def peek(self, address: str, window_days: int = 30) -> Optional[StrategyFingerprint]:
        with self._lock:
            hit = self._cache.get((address, window_days))
            return hit[0] if hit else None

    def get(self, client: Any, address: str, window_days: int
            ) -> Union[StrategyFingerprint, ScoutStatus]:
        key = (address, window_days)
        with self._lock:
            err = self._failed.pop(key, None)
            if err is not None:
                raise err
            hit = self._cache.get(key)
            if hit and self.clock() - hit[1] < self.ttl_s:
                return hit[0]
            if key != self._running and key not in self._pending:
                if len(self._pending) >= self.max_pending:
                    if hit:
                        return hit[0]
                    raise QueueFull(f"{len(self._pending)} fingerprints already queued; retry later")
                self._pending.append(key)
                self._clients[key] = client
            out: Union[StrategyFingerprint, ScoutStatus] = hit[0] if hit else self._status(key)
        self._kick()
        return out

    def _status(self, key: Key) -> ScoutStatus:
        ahead = (0 if key == self._running else
                 list(self._pending).index(key) + (1 if self._running else 0))
        return ScoutStatus(refresh_id=None, state="running", stage="stats", done=0, total=ahead + 1)

    def _kick(self) -> None:
        if not self.autostart:
            return
        with self._lock:
            # drain() clears _thread under this lock in the same critical
            # section that sees the queue empty, so a job queued after that
            # always finds _thread None here and gets a new worker.
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self.drain, name="copycat-fingerprint-jobs",
                                            daemon=True)
            self._thread.start()

    def drain(self) -> None:
        """Run queued jobs until the queue is empty (worker thread body)."""
        while True:
            with self._lock:
                if not self._pending:
                    self._running = None
                    self._thread = None
                    return
                key = self._pending.popleft()
                client = self._clients.pop(key)
                self._running = key
            try:
                fp = client.fingerprint(key[0], key[1])
            except Exception as e:  # noqa: BLE001 -- surfaced to the next GET
                logger.warning("fingerprint %s (%sd) failed: %s", key[0], key[1], e)
                with self._lock:
                    self._failed[key] = e
                    self._running = None
                continue
            with self._lock:
                self._cache.pop(key, None)
                self._cache[key] = (fp, self.clock())     # dict order = age order
                while len(self._cache) > self.max_cached:
                    self._cache.pop(next(iter(self._cache)))
                self._running = None
