"""Gate tests for hl.http: the timeout guard (the actual pathiel bug --
`timeout=None` is passed EXPLICITLY by the SDK, so a `setdefault` guard
never fires) and http_post's failure/rate-limit paths. No real network.
"""
from __future__ import annotations

from hl import http, rate_limit


class _FakeSession:
    """Mimics a requests.Session enough to exercise set_session_timeout:
    records every call to .request(method, url, **kw)."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, dict(kw)))
        return "ok"


class _FakeClient:
    def __init__(self, session):
        self.session = session


# ── set_session_timeout: the actual bug ─────────────────────────────────────

def test_timeout_none_is_overwritten_even_though_key_is_explicitly_present():
    """The SDK calls session.request(..., timeout=self.timeout) where
    self.timeout defaults to None -- the key IS present, just set to None.
    A naive kw.setdefault("timeout", 10) would never fire here. Assert the
    real fix: check the VALUE, not presence."""
    sess = _FakeSession()
    client = http.set_session_timeout(_FakeClient(sess), timeout_s=7.5)
    client.session.request("POST", "http://x", timeout=None)  # SDK's exact call shape
    assert sess.calls[-1][2]["timeout"] == 7.5


def test_explicit_real_timeout_is_not_overwritten():
    sess = _FakeSession()
    client = http.set_session_timeout(_FakeClient(sess), timeout_s=7.5)
    client.session.request("POST", "http://x", timeout=3.0)
    assert sess.calls[-1][2]["timeout"] == 3.0


def test_missing_timeout_kw_is_set_too():
    sess = _FakeSession()
    client = http.set_session_timeout(_FakeClient(sess), timeout_s=7.5)
    client.session.request("POST", "http://x")  # no timeout kw at all
    assert sess.calls[-1][2]["timeout"] == 7.5


def test_default_timeout_s_reads_env(monkeypatch):
    monkeypatch.setenv("COPYCAT_HL_TIMEOUT_S", "4.2")
    sess = _FakeSession()
    client = http.set_session_timeout(_FakeClient(sess))  # no explicit timeout_s
    client.session.request("POST", "http://x", timeout=None)
    assert sess.calls[-1][2]["timeout"] == 4.2


def test_missing_session_attr_is_tolerated():
    class _NoSession:
        pass

    client = http.set_session_timeout(_NoSession())
    assert client is not None  # returned unchanged, no raise


def test_session_request_not_callable_is_tolerated():
    class _BrokenSession:
        request = 123  # not callable -- getattr(client, "session") exists but is broken

    client = http.set_session_timeout(_FakeClient(_BrokenSession()))
    assert client is not None  # best-effort: logs a warning, never raises


# ── http_post ────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class _FakePostSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        if self._exc:
            raise self._exc
        return self._response


def test_http_post_happy_path(monkeypatch):
    fake = _FakePostSession(response=_FakeResponse({"ok": True}))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    out = http.http_post("/info", {"type": "meta"})
    assert out == {"ok": True}
    assert fake.posts[0][0].endswith("/info")
    assert fake.posts[0][2] == 10.0  # default timeout


def test_http_post_passes_base_url_for_network(monkeypatch):
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    fake = _FakePostSession(response=_FakeResponse({}))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    http.http_post("/info", {"type": "meta"})
    assert "testnet" in fake.posts[0][0]


def test_http_post_returns_none_on_exception(monkeypatch):
    fake = _FakePostSession(exc=TimeoutError("read timeout=None"))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    assert http.http_post("/info", {"type": "meta"}) is None


def test_http_post_returns_none_on_http_error(monkeypatch):
    fake = _FakePostSession(response=_FakeResponse({"err": "bad"}, status=500))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    assert http.http_post("/info", {"type": "meta"}) is None


def test_http_post_never_raises_on_bad_json(monkeypatch):
    class _BadJsonResponse(_FakeResponse):
        def json(self):
            raise ValueError("not json")

    fake = _FakePostSession(response=_BadJsonResponse({}))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    assert http.http_post("/info", {"type": "meta"}) is None


def test_http_post_respects_rate_limiter(monkeypatch):
    """A drained bucket makes http_post return None WITHOUT ever touching
    the network -- the limiter is consulted before get_session()."""
    fake = _FakePostSession(response=_FakeResponse({"should": "not be seen"}))
    monkeypatch.setattr(http, "get_session", lambda: fake)
    empty_bucket = rate_limit.TokenBucket(capacity=0, refill_per_sec=0)
    monkeypatch.setattr(rate_limit, "HL_LIMITER", empty_bucket)
    out = http.http_post("/info", {"type": "meta"}, max_wait=0.05)
    assert out is None
    assert fake.posts == []  # never called
