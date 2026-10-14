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

The budget is per IP, and two processes share it: the engine
(`python -m engine`) and discovery (inside the api process today). Two
private 1200/min buckets could together spend 2400/min and draw 429s that
make the engine skip cycles and delay exits. So the default limiter is a
`SharedTokenBucket`: one fcntl-locked file in $COPYCAT_DATA_DIR that every
copycat process on the host draws from, with two priority classes
(COPYCAT_HL_PRIORITY):

  engine      may spend the whole bucket.
  background  may only spend down to a reserve (COPYCAT_HL_RESERVE_FRAC,
              default 0.4 of capacity) and sleeps otherwise, so the engine
              always finds ~40% of the budget waiting for it.

If the file cannot be opened or locked (read-only disk, no fcntl on the
platform) the shared bucket falls back to a private in-process
`TokenBucket` and logs once. Pacing degrades to per-process; nothing breaks.

Per-item surcharges are charged AFTER the response, from the real item
count (`item_surcharge` + `charge`): http_post acquires the base weight
before the call, then charges ceil(n/20) (or ceil(n/60) for candles) once it
knows n. Pre-charging the cap instead billed every userFillsByTime page 120
(the 2000-row max) even when it returned 12 rows. `charge` never waits: the
request already happened, so the bucket may go negative (debt, floored at
-capacity) and every later acquire, in either process, waits for refill to
pay it off. Priority reserve rules apply to acquire, not to charge.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Optional

try:  # POSIX only; on a platform without it the shared bucket falls back
    import fcntl
except ImportError:  # pragma: no cover - not reachable on macOS/Linux
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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
    # the docs list it as "nonUserFundingUpdates"; the request type is this one
    "userNonFundingLedgerUpdates",
})


def endpoint_weight(req_type: Optional[str], item_count: Optional[int] = None) -> int:
    """Weight for one /info `type`: the base weight, plus the documented
    per-item surcharge for `item_count` items when given. http_post charges
    the base before the call and `item_surcharge` after it."""
    return _BASE_WEIGHT.get(req_type or "", _DEFAULT_WEIGHT) + item_surcharge(req_type, item_count)


def item_surcharge(req_type: Optional[str], item_count: Optional[int]) -> int:
    """The per-item part alone: +1 per 20 items (userFillsByTime, ...), +1 per
    60 for candleSnapshot, 0 for every other type or a missing count."""
    if not item_count or item_count <= 0:
        return 0
    if req_type == "candleSnapshot":
        return math.ceil(item_count / 60)
    if req_type in _PER_20_ITEMS:
        return math.ceil(item_count / 20)
    return 0


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

    def charge(self, weight: float) -> None:
        """Deduct weight already spent (a post-response surcharge). Never
        waits; may leave the bucket in debt, floored at -capacity."""
        if weight <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._refill)
            self._last = now
            self._tokens = max(-self._capacity, self._tokens - weight)

    def drain(self) -> None:
        """HL answered 429: our estimate was optimistic. Empty the bucket so
        every caller waits for real refill before trying again. Debt stays."""
        with self._lock:
            self._tokens = min(0.0, self._tokens)
            self._last = time.monotonic()


PRIORITIES = ("engine", "background")
DEFAULT_RESERVE_FRAC = 0.4
BUCKET_FILENAME = "hl_rate.bucket"


def priority() -> str:
    p = (os.environ.get("COPYCAT_HL_PRIORITY") or "engine").strip().lower()
    return p if p in PRIORITIES else "engine"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class SharedTokenBucket:
    """Token bucket whose state lives in one small file shared by every
    copycat process on the host: `"<tokens> <wall_ts>"`, read-modify-written
    under an exclusive `fcntl.flock`. Wall-clock time (not monotonic) because
    monotonic clocks are per-process; a backwards clock step is clamped to
    zero elapsed, a forward step just refills to capacity.

    `priority="background"` may only take tokens while at least
    `reserve_frac * capacity` stays in the bucket afterwards; `"engine"` may
    take everything. Both sleep (up to max_wait) when they cannot proceed.

    Any OSError opening, locking, or writing the file switches this instance
    to a private in-process TokenBucket for the rest of its life (logged
    once): a broken data dir degrades pacing, never the read itself.
    """

    def __init__(self, path: Path, capacity: float, refill_per_sec: float,
                 priority: Optional[str] = "engine", reserve_frac: float = DEFAULT_RESERVE_FRAC):
        """`priority=None`: follow COPYCAT_HL_PRIORITY at EVERY acquire (the
        process-wide default limiter). Audit M1: reading it once at import let
        the api run at "engine" priority when hl happened to be imported (via
        the vault) before the env var was set, so a big MCP plan preview could
        eat the engine's reserve."""
        self.path = Path(path)
        self._capacity = float(capacity)
        self._refill = float(refill_per_sec)
        self._pinned = priority if priority in PRIORITIES else (None if priority is None else "engine")
        self._reserve_frac = max(0.0, min(1.0, float(reserve_frac)))
        self._thread_lock = threading.Lock()
        self._fallback: Optional[TokenBucket] = None

    @property
    def priority(self) -> str:
        return self._pinned or globals()["priority"]()

    @property
    def _reserve(self) -> float:
        return self._reserve_frac * self._capacity if self.priority == "background" else 0.0

    # -- file state ---------------------------------------------------------

    def _fall_back(self, exc: BaseException) -> TokenBucket:
        if self._fallback is None:
            logger.warning(
                f"[hl.rate_limit] shared bucket {self.path} unusable ({exc}); falling back to an "
                f"in-process bucket. Pacing is now per-process, not shared with the other copycat process."
            )
            self._fallback = TokenBucket(self._capacity, self._refill)
        return self._fallback

    def _with_state(self, fn):
        """Run fn(tokens, now) -> new_tokens under the file lock and persist.
        Returns fn's second return value. Raises OSError on file trouble."""
        if fcntl is None:
            raise OSError("fcntl unavailable on this platform")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    raw = os.read(fd, 128).decode("ascii", "replace").split()
                    now = time.time()
                    try:
                        tokens, last = float(raw[0]), float(raw[1])
                        if not (math.isfinite(tokens) and math.isfinite(last)):
                            raise ValueError("non-finite")
                    except (IndexError, ValueError):
                        tokens, last = self._capacity, now   # new or corrupt file: start full
                    elapsed = max(0.0, now - last)
                    # >= -capacity, not >= 0: a post-response charge() may leave debt
                    tokens = min(self._capacity, max(-self._capacity, tokens) + elapsed * self._refill)
                    new_tokens, result = fn(tokens)
                    data = f"{new_tokens:.6f} {now:.6f}".encode("ascii")
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, data)
                    return result
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # -- public -------------------------------------------------------------

    def tokens(self) -> float:
        """Current level (after refill). For tests and ops visibility."""
        if self._fallback is not None:
            return self._fallback._tokens
        try:
            return self._with_state(lambda t: (t, t))
        except OSError as exc:
            return self._fall_back(exc)._tokens

    def acquire(self, weight: int = 20, max_wait: float = 10.0) -> bool:
        if self._fallback is not None:
            return self._fallback.acquire(weight, max_wait=max_wait)
        deadline = time.monotonic() + max_wait
        floor = self._reserve
        while True:
            def take(t: float):
                if t - weight >= floor:
                    return t - weight, 0.0
                return t, (weight + floor - t)   # deficit still to refill

            try:
                deficit = self._with_state(take)
            except OSError as exc:
                remaining = max(0.0, deadline - time.monotonic())
                return self._fall_back(exc).acquire(weight, max_wait=remaining)
            if deficit <= 0:
                return True
            if self._refill <= 0 or weight + floor > self._capacity:
                return False   # can never be satisfied
            sleep_for = deficit / self._refill
            if time.monotonic() + sleep_for > deadline:
                return False
            time.sleep(min(sleep_for, 0.5))

    def charge(self, weight: float) -> None:
        """Deduct weight already spent, shared with every process; never
        waits, may leave debt (floored at -capacity). See module docstring."""
        if weight <= 0:
            return
        if self._fallback is not None:
            self._fallback.charge(weight)
            return
        try:
            self._with_state(lambda t: (max(-self._capacity, t - weight), None))
        except OSError as exc:
            self._fall_back(exc).charge(weight)

    def drain(self) -> None:
        if self._fallback is not None:
            self._fallback.drain()
            return
        try:
            self._with_state(lambda t: (min(0.0, t), None))
        except OSError as exc:
            self._fall_back(exc).drain()


def data_dir() -> Path:
    return Path(os.environ.get("COPYCAT_DATA_DIR", "./data"))


def bucket_path() -> Path:
    """Where the shared bucket lives: COPYCAT_HL_BUCKET_PATH when set, else
    $COPYCAT_DATA_DIR/hl_rate.bucket. The budget is per IP, so every copycat
    process on the host must draw from ONE file. A second stack on the same
    host with its own data dir (an eval, a QA worktree, a second install) gets
    its own full 1200/min by default, and the two together draw 429s on the
    live engine: on 2026-10-14 two throwaway stacks cost a trading engine a
    leader read. Such a stack sets COPYCAT_HL_BUCKET_PATH to the live data
    dir's hl_rate.bucket (and COPYCAT_HL_PRIORITY=background) and then only
    spends what the engine's reserve leaves."""
    p = (os.environ.get("COPYCAT_HL_BUCKET_PATH") or "").strip()
    return Path(p) if p else data_dir() / BUCKET_FILENAME


def build_default_limiter():
    """The process-wide limiter: a SharedTokenBucket at `bucket_path()` with
    this process's priority class. Capacity/refill default to the full
    documented budget (1200, 20/s) and stay env-tunable
    (COPYCAT_HL_RATE_CAPACITY / _REFILL_PER_SEC). The file is only touched
    on first acquire, so importing this module has no filesystem side effect."""
    return SharedTokenBucket(
        path=bucket_path(),
        capacity=_env_float("COPYCAT_HL_RATE_CAPACITY", 1200.0),
        refill_per_sec=_env_float("COPYCAT_HL_RATE_REFILL_PER_SEC", 20.0),
        priority=None,             # dynamic: COPYCAT_HL_PRIORITY at every acquire (audit M1)
        reserve_frac=_env_float("COPYCAT_HL_RESERVE_FRAC", DEFAULT_RESERVE_FRAC),
    )


HL_LIMITER = build_default_limiter()


def set_priority(p: str) -> None:
    """Rebuild HL_LIMITER for priority class `p` ("engine" | "background").
    For a process that decides its class after `hl` was imported (env is
    read at import otherwise). Callers going through `rate_limit.HL_LIMITER`
    (hl.http does) pick the new bucket up on their next call."""
    global HL_LIMITER
    os.environ["COPYCAT_HL_PRIORITY"] = p
    HL_LIMITER = build_default_limiter()
