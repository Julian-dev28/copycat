"""Shared fixtures for services/hl's gate tests: every module-level cache
and singleton this package owns gets reset between tests, and the
environment starts clean so one test's env vars can't leak into the next.
"""
from __future__ import annotations

import pytest
from hl import meta, sdk
from hl import venue as venue_mod
from hl.http import reset_session
from hl.rate_limit import TokenBucket

_ENV_KEYS = (
    "COPYCAT_NETWORK", "COPYCAT_AGENT_KEY", "COPYCAT_ACCOUNT_ADDRESS",
    "COPYCAT_HL_TIMEOUT_S", "COPYCAT_HL_DEXES", "COPYCAT_HL_RATE_CAPACITY",
    "COPYCAT_HL_RATE_REFILL_PER_SEC", "COPYCAT_HL_META_TTL_S",
    "COPYCAT_HL_DEX_LIST_TTL_S", "COPYCAT_HL_SPOT_PRICE_TTL_S",
    "COPYCAT_HL_ASSET_CTX_TTL_S", "COPYCAT_HL_L2_BOOK_TTL_S",
    "COPYCAT_HL_PRIORITY", "COPYCAT_HL_RESERVE_FRAC", "COPYCAT_HL_CLOSE_SLIPPAGE_PCT",
)


class _NoNetwork:
    def post(self, url, **kw):
        raise ConnectionError(f"gate tests must not hit the network: POST {url}")


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, request, tmp_path):
    """Runs around every test: clear copycat's HL env vars, reset the meta
    caches and the Exchange singleton, and give every test an unlimited,
    instant token bucket unless it explicitly wants to test rate limiting."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    # Credentials resolve through $COPYCAT_DATA_DIR/vault when one exists: never
    # let a test see the repo's real ./data vault.
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path / "data"))
    meta.reset_caches()
    sdk.reset()
    reset_session()
    venue_mod._abstraction.clear()
    venue_mod._active_dexes.clear()
    venue_mod._last_full_scan.clear()
    # Fresh, effectively-infinite bucket by default: a test exercising
    # http_post for something unrelated to rate limiting must never be
    # throttled by a previous test's partially-drained bucket.
    # Gate tests never touch the network: any http_post a test did not fake
    # fails like a dead connection (http_post turns that into None).
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr("hl.http.get_session", lambda: _NoNetwork())
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
