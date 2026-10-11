"""COPYCAT_HL_BASE_URL / COPYCAT_HL_STATS_URL: the e2e lane's mock Hyperliquid.
Loopback only: a remote override is ignored (a browser-signed withdraw posted
to someone else's server could be replayed on the real chain)."""
from __future__ import annotations

import pytest
from hl import env, http
from hyperliquid.utils import constants


def test_default_is_real_mainnet():
    assert env.base_url() == constants.MAINNET_API_URL
    assert env.stats_url() == "https://stats-data.hyperliquid.xyz"


def test_testnet_without_override(monkeypatch):
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    assert env.base_url() == constants.TESTNET_API_URL


@pytest.mark.parametrize("url", ["http://127.0.0.1:9001", "http://localhost:9001/", "http://[::1]:9001"])
def test_loopback_override_wins(monkeypatch, url):
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", url)
    assert env.base_url() == url.rstrip("/")
    # the stats host follows the base override unless set on its own
    assert env.stats_url() == url.rstrip("/")


def test_stats_override_on_its_own(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", "http://127.0.0.1:9001")
    monkeypatch.setenv("COPYCAT_HL_STATS_URL", "http://127.0.0.1:9002")
    assert env.stats_url() == "http://127.0.0.1:9002"


@pytest.mark.parametrize("url", [
    "https://evil.example.com", "http://10.0.0.5:9001", "ftp://127.0.0.1", "127.0.0.1:9001",
    "http://127.0.0.1.evil.com", "http://[bad",
])
def test_remote_or_malformed_override_is_ignored(monkeypatch, caplog, url):
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", url)
    assert env.base_url() == constants.MAINNET_API_URL
    assert env.stats_url() == "https://stats-data.hyperliquid.xyz"
    assert "not a loopback" in caplog.text


def test_http_post_goes_to_the_override(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", "http://127.0.0.1:9001")
    seen = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": 1}

        def raise_for_status(self):
            return None

    class _Sess:
        def post(self, url, **kw):
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(http, "get_session", lambda: _Sess())
    assert http.http_post("/info", {"type": "allMids"}) == {"ok": 1}
    assert seen["url"] == "http://127.0.0.1:9001/info"


def test_leaderboard_uses_stats_url(monkeypatch):
    from hl import venue as venue_mod
    monkeypatch.setenv("COPYCAT_HL_BASE_URL", "http://127.0.0.1:9001")
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"leaderboardRows": []}

    def _get(url, timeout):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(venue_mod.requests, "get", _get)
    assert venue_mod.HlVenue().leaderboard() == []
    assert seen["url"] == "http://127.0.0.1:9001/Mainnet/leaderboard"
