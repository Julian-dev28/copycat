"""Strategy-thesis routes + market candles against fakes. The fingerprint
queue runs with autostart=False (conftest `jobs`), so "building" and "done"
are driven by jobs.drain(), never by thread timing."""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from api.deps import get_market_client, get_thesis_client
from api.fingerprint_jobs import FingerprintJobs, QueueFull
from api.thesis_client import FingerprintFailed

from api_fakes import (
    ADDR_A,
    ADDR_B,
    FakeMarketClient,
    FakeThesisClient,
    UnavailableMarketClient,
    UnavailableThesisClient,
    make_fingerprint,
)
from contracts.models import Thesis

FP = f"/api/scout/traders/{ADDR_A}/fingerprint"
TRADES = f"/api/scout/traders/{ADDR_A}/trades"
THESIS = f"/api/scout/traders/{ADDR_A}/thesis"
CANDLES = "/api/market/candles"
BODY = {"title": "Breakout buyer", "markdown": "# Thesis\nBuys 20-bar highs.", "author": "claude via mcp"}
CANDLE_Q = {"coin": "BTC", "interval": "1h", "start_ms": 0, "end_ms": 3_600_000 * 10}

ROUTES = [("GET", FP, None), ("GET", TRADES, None), ("GET", THESIS, None),
          ("PUT", THESIS, BODY), ("GET", CANDLES, None)]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str, body) -> None:
    params = CANDLE_Q if path == CANDLES else None
    assert client.request(method, path, json=body, params=params).status_code == 401


@pytest.mark.parametrize("bad", ["0x12", "zz", "0x" + "g" * 40])
def test_bad_address_404(client: TestClient, auth_headers: dict, bad: str) -> None:
    base = f"/api/scout/traders/{bad}"
    for path in ("/fingerprint", "/trades", "/thesis"):
        assert client.get(base + path, headers=auth_headers).status_code == 404
    assert client.put(base + "/thesis", headers=auth_headers, json=BODY).status_code == 404


# ── fingerprint / trades ─────────────────────────────────────────────────────

def test_fingerprint_202_then_200_and_never_inline(client: TestClient, auth_headers: dict,
                                                   jobs: FingerprintJobs, fake_thesis: FakeThesisClient) -> None:
    r = client.get(FP, headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["state"] == "running"
    assert fake_thesis.fingerprint_calls == []          # queued, not computed in the request
    assert client.get(FP, headers=auth_headers).status_code == 202   # deduped, still one job
    jobs.drain()
    assert fake_thesis.fingerprint_calls == [(ADDR_A, 30)]
    r = client.get(FP, headers=auth_headers)
    assert r.status_code == 200 and r.json()["address"] == ADDR_A and r.json()["trips_analyzed"] == 40


def test_fingerprint_window_days(client: TestClient, auth_headers: dict, jobs: FingerprintJobs,
                                 fake_thesis: FakeThesisClient) -> None:
    client.get(FP + "?window_days=14", headers=auth_headers)
    jobs.drain()
    assert fake_thesis.fingerprint_calls == [(ADDR_A, 14)]
    assert client.get(FP + "?window_days=14", headers=auth_headers).json()["window_days"] == 14
    assert client.get(FP, headers=auth_headers).status_code == 202     # 30d is its own key
    for bad in ("6", "91", "x"):
        assert client.get(FP + f"?window_days={bad}", headers=auth_headers).status_code == 422


def test_fingerprint_stale_served_while_refreshing(client: TestClient, auth_headers: dict, jobs: FingerprintJobs,
                                                   fake_thesis: FakeThesisClient, clock) -> None:
    client.get(FP, headers=auth_headers)
    jobs.drain()
    first = client.get(FP, headers=auth_headers).json()["as_of_ms"]
    clock.t += jobs.ttl_s + 1
    r = client.get(FP, headers=auth_headers)
    assert r.status_code == 200 and r.json()["as_of_ms"] == first      # stale, not a 202
    jobs.drain()
    assert len(fake_thesis.fingerprint_calls) == 2
    assert client.get(FP, headers=auth_headers).json()["as_of_ms"] != first


def test_fingerprint_failure_502_once_then_retried(client: TestClient, auth_headers: dict, jobs: FingerprintJobs,
                                                   fake_thesis: FakeThesisClient) -> None:
    fake_thesis.fail_with = FingerprintFailed("child died")
    client.get(FP, headers=auth_headers)
    jobs.drain()
    r = client.get(FP, headers=auth_headers)
    assert r.status_code == 502 and "child died" in r.json()["detail"]
    fake_thesis.fail_with = None
    assert client.get(FP, headers=auth_headers).status_code == 202     # re-queued
    jobs.drain()
    assert client.get(FP, headers=auth_headers).status_code == 200


def test_fingerprint_unavailable_503(client: TestClient, auth_headers: dict, jobs: FingerprintJobs,
                                     app) -> None:
    app.dependency_overrides[get_thesis_client] = lambda: UnavailableThesisClient()
    client.get(FP, headers=auth_headers)
    jobs.drain()
    assert client.get(FP, headers=auth_headers).status_code == 503
    assert client.get(THESIS, headers=auth_headers).status_code == 503
    assert client.put(THESIS, headers=auth_headers, json=BODY).status_code == 503


def test_fingerprint_queue_full_429(client: TestClient, auth_headers: dict) -> None:
    for i in range(3):                                  # conftest max_pending=3
        addr = "0x" + f"{i:x}" * 40
        assert client.get(f"/api/scout/traders/{addr}/fingerprint", headers=auth_headers).status_code == 202
    r = client.get(f"/api/scout/traders/{ADDR_B}/fingerprint", headers=auth_headers)
    assert r.status_code == 429


def test_trades_are_fingerprint_examples(client: TestClient, auth_headers: dict, jobs: FingerprintJobs) -> None:
    assert client.get(TRADES, headers=auth_headers).status_code == 202
    jobs.drain()
    r = client.get(TRADES, headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 8
    assert "context" in r.json()[0] and r.json()[0]["context"]["hour_utc"] == 0
    assert len(client.get(TRADES + "?limit=3", headers=auth_headers).json()) == 3
    for bad in ("0", "9"):
        assert client.get(TRADES + f"?limit={bad}", headers=auth_headers).status_code == 422


# ── thesis ───────────────────────────────────────────────────────────────────

def _t(source: str, created: int, title: str = "t") -> Thesis:
    return Thesis(address=ADDR_A, source=source, created_ms=created, title=title, markdown="m")


def test_get_thesis_latest_per_source_ta_first(client: TestClient, auth_headers: dict,
                                               fake_thesis: FakeThesisClient) -> None:
    assert client.get(THESIS, headers=auth_headers).json() == []
    fake_thesis.stored = [_t("claude_code", 5, "old cc"), _t("ta", 1, "old ta"), _t("claude_code", 9, "new cc"),
                          _t("ta", 3, "new ta"),
                          Thesis(address=ADDR_B, source="ta", created_ms=99, title="other", markdown="m")]
    r = client.get(THESIS, headers=auth_headers).json()
    assert [(t["source"], t["title"]) for t in r] == [("ta", "new ta"), ("claude_code", "new cc")]


def test_put_thesis_saves_claude_code_with_server_fields(client: TestClient, auth_headers: dict,
                                                         fake_thesis: FakeThesisClient, jobs: FingerprintJobs) -> None:
    r = client.put(f"/api/scout/traders/{ADDR_A.upper().replace('0X', '0x')}/thesis", headers=auth_headers, json=BODY)
    assert r.status_code == 200
    saved = fake_thesis.saved[-1]
    assert saved.source == "claude_code" and saved.address == ADDR_A
    assert saved.created_ms > 1_600_000_000_000 and saved.author == "claude via mcp"
    assert saved.fingerprint_as_of_ms is None
    assert r.json()["source"] == "claude_code"
    # with a cached 30d fingerprint, the thesis links to it
    client.get(FP, headers=auth_headers)
    jobs.drain()
    client.put(THESIS, headers=auth_headers, json={"title": "x", "markdown": "y"})
    assert fake_thesis.saved[-1].fingerprint_as_of_ms == jobs.peek(ADDR_A).as_of_ms
    assert fake_thesis.saved[-1].author is None


@pytest.mark.parametrize("body", [
    {**BODY, "source": "ta"},
    {**BODY, "source": "claude_code"},
    {**BODY, "created_ms": 1},
    {**BODY, "address": ADDR_B},
    {**BODY, "markdown": "x" * 20_001},
    {**BODY, "markdown": ""},
    {**BODY, "title": ""},
    {**BODY, "title": "t" * 201},
    {"title": "no markdown"},
])
def test_put_thesis_rejects_422(client: TestClient, auth_headers: dict, fake_thesis: FakeThesisClient,
                                body: dict) -> None:
    assert client.put(THESIS, headers=auth_headers, json=body).status_code == 422
    assert fake_thesis.saved == []


def test_put_thesis_markdown_at_limit_ok(client: TestClient, auth_headers: dict) -> None:
    assert client.put(THESIS, headers=auth_headers, json={**BODY, "markdown": "x" * 20_000}).status_code == 200


# ── candles ──────────────────────────────────────────────────────────────────

def test_candles_ok(client: TestClient, auth_headers: dict, fake_market: FakeMarketClient) -> None:
    r = client.get(CANDLES, params=CANDLE_Q, headers=auth_headers)
    assert r.status_code == 200 and r.json()[0] == {"t_ms": 0, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
    assert fake_market.calls == [("BTC", "1h", 0, 36_000_000)]


def test_candles_cap_is_inclusive_5000_bars(client: TestClient, auth_headers: dict) -> None:
    ok = {**CANDLE_Q, "interval": "1m", "end_ms": 60_000 * 4999}
    assert client.get(CANDLES, params=ok, headers=auth_headers).status_code == 200
    over = {**CANDLE_Q, "interval": "1m", "end_ms": 60_000 * 5000}
    assert client.get(CANDLES, params=over, headers=auth_headers).status_code == 422


@pytest.mark.parametrize("patch", [
    {"interval": "7m"}, {"interval": "1w"}, {"interval": ""},
    {"end_ms": 0}, {"start_ms": 100, "end_ms": 50}, {"start_ms": -1},
    {"coin": ""}, {"coin": "BTC;DROP"}, {"coin": "x" * 33}, {"extra": "1"},
])
def test_candles_422(client: TestClient, auth_headers: dict, fake_market: FakeMarketClient, patch: dict) -> None:
    assert client.get(CANDLES, params={**CANDLE_Q, **patch}, headers=auth_headers).status_code == 422
    assert fake_market.calls == []


def test_candles_missing_params_422(client: TestClient, auth_headers: dict) -> None:
    assert client.get(CANDLES, params={"coin": "BTC"}, headers=auth_headers).status_code == 422


def test_candles_503(client: TestClient, auth_headers: dict, app) -> None:
    app.dependency_overrides[get_market_client] = lambda: UnavailableMarketClient()
    assert client.get(CANDLES, params=CANDLE_Q, headers=auth_headers).status_code == 503


# ── FingerprintJobs with its real worker thread ──────────────────────────────

def test_jobs_worker_thread_runs_one_at_a_time_and_restarts() -> None:
    gate = threading.Event()
    running = []
    max_seen = [0]

    class Slow:
        def fingerprint(self, address: str, window_days: int):
            running.append(address)
            max_seen[0] = max(max_seen[0], len(running))
            gate.wait(2)
            running.remove(address)
            return make_fingerprint(address, window_days)

    jobs = FingerprintJobs()
    assert jobs.get(Slow(), ADDR_A, 30).state == "running"
    st = jobs.get(Slow(), ADDR_B, 30)
    assert st.state == "running" and st.total == 2       # one ahead of it
    gate.set()
    for _ in range(200):
        if jobs.peek(ADDR_A) and jobs.peek(ADDR_B):
            break
        threading.Event().wait(0.005)
    assert jobs.peek(ADDR_A) and jobs.peek(ADDR_B) and max_seen[0] == 1
    # worker exited on an empty queue; a new job must start a new one
    jobs.ttl_s = 0
    jobs.get(Slow(), ADDR_A, 30)
    for _ in range(200):
        if jobs._thread is None and not jobs._pending:
            break
        threading.Event().wait(0.005)
    assert jobs._thread is None and not jobs._pending


def test_jobs_cache_bounded() -> None:
    jobs = FingerprintJobs(autostart=False, max_cached=2)
    c = FakeThesisClient()
    for a in (ADDR_A, ADDR_B, "0x" + "e" * 40):
        jobs.get(c, a, 30)
    jobs.drain()
    assert jobs.peek(ADDR_A) is None and jobs.peek(ADDR_B) is not None


def test_jobs_queue_full_serves_stale_instead() -> None:
    jobs = FingerprintJobs(autostart=False, max_pending=1, ttl_s=0)
    c = FakeThesisClient()
    jobs.get(c, ADDR_A, 30)
    jobs.drain()
    jobs.get(c, ADDR_B, 30)                               # fills the queue
    assert jobs.get(c, ADDR_A, 30).address == ADDR_A      # stale beats 429
    with pytest.raises(QueueFull):
        jobs.get(c, "0x" + "e" * 40, 30)
