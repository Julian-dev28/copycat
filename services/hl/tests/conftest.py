"""Shared fixtures for services/hl's gate tests: every module-level cache
and singleton this package owns gets reset between tests, and the
environment starts clean so one test's env vars can't leak into the next.
"""
from __future__ import annotations

import pytest
from hl import meta, sdk
from hl.http import reset_session
from hl.rate_limit import TokenBucket

_ENV_KEYS = (
    "COPYCAT_NETWORK", "COPYCAT_AGENT_KEY", "COPYCAT_ACCOUNT_ADDRESS",
    "COPYCAT_HL_TIMEOUT_S", "COPYCAT_HL_DEXES", "COPYCAT_HL_RATE_CAPACITY",
    "COPYCAT_HL_RATE_REFILL_PER_SEC", "COPYCAT_HL_META_TTL_S",
    "COPYCAT_HL_DEX_LIST_TTL_S", "COPYCAT_HL_SPOT_PRICE_TTL_S",
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Runs around every test: clear copycat's HL env vars, reset the meta
    caches and the Exchange singleton, and give every test an unlimited,
    instant token bucket unless it explicitly wants to test rate limiting."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    meta.reset_caches()
    sdk.reset()
    reset_session()
    # Fresh, effectively-infinite bucket by default: a test exercising
    # http_post for something unrelated to rate limiting must never be
    # throttled by a previous test's partially-drained bucket.
    monkeypatch.setattr("hl.rate_limit.HL_LIMITER", TokenBucket(capacity=1_000_000, refill_per_sec=1_000_000))
    yield
    meta.reset_caches()
    sdk.reset()
    reset_session()


@pytest.fixture
def write_creds(monkeypatch):
    """Sets a syntactically-valid (not real) agent key + account address so
    write-path tests can get past the has_write_creds() gate."""
    monkeypatch.setenv("COPYCAT_AGENT_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", "0x" + "22" * 20)
