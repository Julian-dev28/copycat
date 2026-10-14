"""Scout routes (spec section 8) against FakeScoutClient: auth on every
route, query validation, 404 / 202 / 409 / 503, in_book from Settings,
what-if one at a time on the current settings file."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.deps import get_scout_client
from api.routes import scout as scout_routes

from api_fakes import ADDR_A, ADDR_B, ADDR_BUILDING, FakeScoutClient, UnavailableScoutClient

ADDR_UNKNOWN = "0x" + "d" * 40
WHAT_IF_BODY = {"sim_equity_usd": 1000.0, "override": {"leverage": 3}}
SIM_TERMS_BODY = {"use_live_settings": False, "sim_equity_usd": 2000.0, "allocation_usd": 250.0,
                  "exposure_mode": "target", "target_leverage": 8, "leverage_mode": "fixed", "leverage": 8,
                  "margin_mode": "isolated", "max_worse_entry_pct": 15.0, "small_account_mode": "bump"}

ROUTES = [
    ("GET", "/api/scout/traders", None),
    ("GET", f"/api/scout/traders/{ADDR_A}", None),
    ("GET", f"/api/scout/traders/{ADDR_A}/fills", None),
    ("GET", f"/api/scout/traders/{ADDR_A}/orders", None),
    ("POST", f"/api/scout/traders/{ADDR_A}/what-if", WHAT_IF_BODY),
    ("GET", "/api/scout/presets", None),
    ("GET", "/api/scout/sim-terms", None),
    ("PUT", "/api/scout/sim-terms", SIM_TERMS_BODY),
    ("GET", "/api/scout/status", None),
    ("POST", "/api/scout/refresh", None),
    ("GET", "/api/scout/custom", None),
    ("POST", "/api/scout/custom", {"address": ADDR_A}),
]


# ── auth / threadpool ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_scout_route_requires_auth(client: TestClient, method: str, path: str, body) -> None:
    assert client.request(method, path, json=body).status_code == 401
    bad = {"Authorization": "Bearer nope-nope-nope-nope-nope-nope-nope"}
    assert client.request(method, path, json=body, headers=bad).status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_scout_route_ok_with_auth(client: TestClient, auth_headers: dict,
                                        method: str, path: str, body) -> None:
    assert client.request(method, path, json=body, headers=auth_headers).status_code in (200, 201)


def test_scout_routes_are_sync_so_they_run_on_the_threadpool() -> None:
    """A sync `def` route runs via run_in_threadpool; an `async def` one
    would run a slow Scout read (or a what-if sim) on the event loop and
    stall /api/engine/halt and close-all behind it."""
    for r in scout_routes.router.routes:
        assert not asyncio.iscoroutinefunction(r.endpoint), r.path


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_scout_route_503_when_scout_missing(client: TestClient, auth_headers: dict, app,
                                                  method: str, path: str, body) -> None:
    app.dependency_overrides[get_scout_client] = lambda: UnavailableScoutClient()
    assert client.request(method, path, json=body, headers=auth_headers).status_code == 503


# ── list ─────────────────────────────────────────────────────────────────────

def test_traders_defaults_passed_to_discovery(client: TestClient, auth_headers: dict,
                                              fake_scout: FakeScoutClient) -> None:
    r = client.get("/api/scout/traders", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 2
    q = fake_scout.queries[-1]
    assert q == {
        "window": "30d", "preset": "all", "coin": [], "min_av": None, "max_av": None,
        "min_pnl": None, "max_pnl": None, "style": [], "min_fit": None, "max_fit": None,
        "max_dd": None, "min_trips": None, "active_within_h": None, "hide_flagged": False,
        "q": None, "sort": "fit", "order": "desc", "limit": 50, "offset": 0,
    }


def test_traders_every_filter_reaches_discovery(client: TestClient, auth_headers: dict,
                                                fake_scout: FakeScoutClient) -> None:
    params = [
        ("window", "7d"), ("preset", "coin:xyz:TSLA"), ("coin", "BTC"), ("coin", "ETH"),
        ("coin", "BTC"), ("min_av", "10000"), ("max_av", "1e6"), ("min_pnl", "-5"),
        ("max_pnl", "500"), ("style", "swing"), ("style", "scalp"), ("min_fit", "40"),
        ("max_fit", "90"), ("max_dd", "25"), ("min_trips", "5"), ("active_within_h", "24"),
        ("hide_flagged", "true"), ("q", " 0xabc "), ("sort", "last_active"), ("order", "asc"),
        ("limit", "200"), ("offset", "400"),
    ]
    r = client.get("/api/scout/traders", params=params, headers=auth_headers)
    assert r.status_code == 200, r.text
    q = fake_scout.queries[-1]
    assert q["window"] == "7d" and q["preset"] == "coin:xyz:TSLA"
    assert q["coin"] == ["BTC", "ETH"]                    # deduped, order kept
    assert q["style"] == ["swing", "scalp"]
    assert (q["min_av"], q["max_av"], q["min_pnl"], q["max_pnl"]) == (10000, 1e6, -5, 500)
    assert (q["min_fit"], q["max_fit"], q["max_dd"]) == (40, 90, 25)
    assert (q["min_trips"], q["active_within_h"], q["hide_flagged"]) == (5, 24, True)
    assert q["q"] == "0xabc"
    assert (q["sort"], q["order"], q["limit"], q["offset"]) == ("last_active", "asc", 200, 400)


@pytest.mark.parametrize("params", [
    {"window": "90d"},
    {"preset": "nope"},
    {"preset": "coin:"},
    {"style": "yolo"},
    {"min_fit": "-1"},
    {"max_fit": "101"},
    {"min_fit": "80", "max_fit": "20"},
    {"min_av": "5", "max_av": "1"},
    {"min_pnl": "5", "max_pnl": "1"},
    {"min_av": "-1"},
    {"max_dd": "-1"},
    {"max_dd": "101"},
    {"min_trips": "-1"},
    {"active_within_h": "0"},
    {"limit": "0"},
    {"limit": "201"},
    {"offset": "-1"},
    {"sort": "pnl_desc"},
    {"order": "up"},
    {"q": ""},
    {"q": "x" * 65},
    {"hide_flagged": "maybe"},
    {"min_av": "abc"},
    {"typo_filter": "1"},
])
def test_traders_invalid_query_is_422(client: TestClient, auth_headers: dict,
                                      fake_scout: FakeScoutClient, params: dict) -> None:
    r = client.get("/api/scout/traders", params=params, headers=auth_headers)
    assert r.status_code == 422, (params, r.text)
    assert fake_scout.queries == []                       # never reached discovery


def test_traders_in_book_filled_from_settings(client: TestClient, auth_headers: dict) -> None:
    rows = client.get("/api/scout/traders", headers=auth_headers).json()["rows"]
    assert [r["in_book"] for r in rows] == [False, False]  # fake says True; api overrides
    assert client.post("/api/leaders", headers=auth_headers,
                       json={"address": ADDR_B.upper().replace("0X", "0x")}).status_code == 200
    rows = client.get("/api/scout/traders", headers=auth_headers).json()["rows"]
    assert {r["address"]: r["in_book"] for r in rows} == {ADDR_A: False, ADDR_B: True}


def test_traders_etag_and_304(client: TestClient, auth_headers: dict,
                              fake_scout: FakeScoutClient) -> None:
    r = client.get("/api/scout/traders", headers=auth_headers)
    tag = r.headers["etag"]
    assert tag.startswith('W/"r1:h1:')
    r2 = client.get("/api/scout/traders", headers={**auth_headers, "If-None-Match": tag})
    assert r2.status_code == 304 and r2.content == b""
    # new refresh -> new tag
    fake_scout.refresh_id = "r2"
    r3 = client.get("/api/scout/traders", headers={**auth_headers, "If-None-Match": tag})
    assert r3.status_code == 200 and r3.headers["etag"] != tag
    # book change -> new tag, so a cached in_book can't survive "Add to book"
    tag3 = r3.headers["etag"]
    client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A})
    r4 = client.get("/api/scout/traders", headers={**auth_headers, "If-None-Match": tag3})
    assert r4.status_code == 200 and r4.headers["etag"] != tag3


# ── profile ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["0x123", "nothex", "0x" + "g" * 40, "0x" + "a" * 41])
def test_profile_invalid_address_404(client: TestClient, auth_headers: dict, bad: str) -> None:
    for suffix in ("", "/fills", "/orders"):
        assert client.get(f"/api/scout/traders/{bad}{suffix}", headers=auth_headers).status_code == 404
    r = client.post(f"/api/scout/traders/{bad}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
    assert r.status_code == 404


def test_profile_ok_normalizes_address_and_fills_in_book(client: TestClient, auth_headers: dict) -> None:
    r = client.get(f"/api/scout/traders/{ADDR_A.upper().replace('0X', '0x')}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["row"]["address"] == ADDR_A
    assert r.json()["row"]["in_book"] is False
    client.post("/api/leaders", headers=auth_headers, json={"address": ADDR_A})
    assert client.get(f"/api/scout/traders/{ADDR_A}", headers=auth_headers).json()["row"]["in_book"] is True


def test_profile_being_built_is_202_with_status(client: TestClient, auth_headers: dict) -> None:
    r = client.get(f"/api/scout/traders/{ADDR_BUILDING}", headers=auth_headers)
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "running" and body["stage"] == "stats" and body["total"] == 2


def test_profile_no_data_is_404(client: TestClient, auth_headers: dict) -> None:
    assert client.get(f"/api/scout/traders/{ADDR_UNKNOWN}", headers=auth_headers).status_code == 404


# ── fills / orders ───────────────────────────────────────────────────────────

def test_fills_paging_params(client: TestClient, auth_headers: dict, fake_scout: FakeScoutClient) -> None:
    r = client.get(f"/api/scout/traders/{ADDR_A}/fills", headers=auth_headers)
    assert r.status_code == 200 and r.json()[0]["coin"] == "BTC"
    assert fake_scout.fills_calls[-1] == (ADDR_A, None, 100)
    r = client.get(f"/api/scout/traders/{ADDR_A}/fills?before_ms=123&limit=500", headers=auth_headers)
    assert r.status_code == 200
    assert fake_scout.fills_calls[-1] == (ADDR_A, 123, 500)
    for q in ("limit=0", "limit=501", "before_ms=-1", "before_ms=x"):
        assert client.get(f"/api/scout/traders/{ADDR_A}/fills?{q}", headers=auth_headers).status_code == 422


def test_orders_typed(client: TestClient, auth_headers: dict) -> None:
    r = client.get(f"/api/scout/traders/{ADDR_A}/orders", headers=auth_headers)
    assert r.status_code == 200
    o = r.json()[0]
    assert (o["oid"], o["limit_px"], o["notional_usd"], o["reduce_only"]) == (7, 100.0, 100.0, False)


# ── what-if ──────────────────────────────────────────────────────────────────

def test_what_if_uses_current_settings_file(client: TestClient, auth_headers: dict,
                                            fake_scout: FakeScoutClient) -> None:
    client.patch("/api/settings", headers=auth_headers, json={"leverage": 7, "fixed_margin_usd": 3})
    r = client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
    assert r.status_code == 200
    assert r.json()["score"]["address"] == ADDR_A
    address, settings, equity, override = fake_scout.what_if_calls[-1]
    assert address == ADDR_A
    assert settings.leverage == 7 and settings.fixed_margin_usd == 3
    assert equity == 1000.0 and override.leverage == 3


@pytest.mark.parametrize("body", [
    {"sim_equity_usd": 0, "override": {}},
    {"sim_equity_usd": -5, "override": {}},
    {"override": {}},
    {"sim_equity_usd": 100},
    {"sim_equity_usd": 100, "override": {"leverage": 0}},
    {"sim_equity_usd": 100, "override": {"leverage": 51}},
])
def test_what_if_invalid_body_422(client: TestClient, auth_headers: dict,
                                  fake_scout: FakeScoutClient, body: dict) -> None:
    r = client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=body)
    assert r.status_code == 422
    assert fake_scout.what_if_calls == []


def test_what_if_one_at_a_time_409(client: TestClient, auth_headers: dict, app,
                                   fake_scout: FakeScoutClient) -> None:
    lock = app.state.scout_what_if_lock
    assert lock.acquire(blocking=False)                   # a what-if "in flight"
    try:
        r = client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
        assert r.status_code == 409
        assert fake_scout.what_if_calls == []
    finally:
        lock.release()
    r = client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
    assert r.status_code == 200


def test_what_if_holds_lock_while_running_and_releases_after(client: TestClient, auth_headers: dict,
                                                             app, fake_scout: FakeScoutClient) -> None:
    lock = app.state.scout_what_if_lock
    seen = []
    fake_scout.what_if_hook = lambda: seen.append(lock.locked())
    client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
    assert seen == [True] and not lock.locked()


def test_what_if_discovery_busy_409_and_lock_released(client: TestClient, auth_headers: dict, app,
                                                      fake_scout: FakeScoutClient) -> None:
    fake_scout.what_if_busy = True
    r = client.post(f"/api/scout/traders/{ADDR_A}/what-if", headers=auth_headers, json=WHAT_IF_BODY)
    assert r.status_code == 409
    assert not app.state.scout_what_if_lock.locked()


# ── presets / status / refresh ───────────────────────────────────────────────

def test_presets(client: TestClient, auth_headers: dict) -> None:
    r = client.get("/api/scout/presets", headers=auth_headers)
    assert r.json() == {"refresh_id": "r1", "coins": ["BTC"], "coin_counts": {"BTC": 2},
                        "hip3_count": 1, "total": 2, "departed_30d": 0, "departed_liquidated_30d": 0, "custom": 0}


def test_status_and_refresh(client: TestClient, auth_headers: dict) -> None:
    assert client.get("/api/scout/status", headers=auth_headers).json()["state"] == "idle"
    r = client.post("/api/scout/refresh", headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "running"
    assert client.get("/api/scout/status", headers=auth_headers).json()["state"] == "running"


def test_refresh_while_running_409(client: TestClient, auth_headers: dict,
                                   fake_scout: FakeScoutClient) -> None:
    fake_scout.refresh_busy = True
    r = client.post("/api/scout/refresh", headers=auth_headers)
    assert r.status_code == 409
    assert "already running" in r.json()["detail"]


# ── sim terms (v16) ──────────────────────────────────────────────────────────

def test_sim_terms_get_default_then_put_round_trips(client: TestClient, auth_headers: dict, app) -> None:
    fake = FakeScoutClient()
    app.dependency_overrides[get_scout_client] = lambda: fake
    r = client.get("/api/scout/sim-terms", headers=auth_headers)
    assert r.status_code == 200
    default = r.json()
    assert default["use_live_settings"] is False and default["allocation_usd"] == 100.0
    assert default["sim_equity_usd"] == 1000.0 and default["leverage"] == 3
    assert default["exposure_mode"] == "target" and default["leverage_mode"] == "fixed"
    r = client.put("/api/scout/sim-terms", json=SIM_TERMS_BODY, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == SIM_TERMS_BODY
    assert client.get("/api/scout/sim-terms", headers=auth_headers).json() == SIM_TERMS_BODY


@pytest.mark.parametrize("bad", [{"allocation_usd": -1}, {"leverage": 0}, {"leverage": 999},
                                 {"max_worse_entry_pct": 150}, {"sim_equity_usd": 0}, {"exposure_mode": "nope"}])
def test_sim_terms_put_validates_like_leader_override(client: TestClient, auth_headers: dict, bad: dict) -> None:
    assert client.put("/api/scout/sim-terms", json=bad, headers=auth_headers).status_code == 422


def test_sim_terms_put_requires_auth(client: TestClient) -> None:
    assert client.put("/api/scout/sim-terms", json={}).status_code == 401


# ── custom wallets (v15) ─────────────────────────────────────────────────────

def test_custom_wallet_add_list_remove(client: TestClient, auth_headers: dict, app) -> None:
    fake = FakeScoutClient()
    app.dependency_overrides[get_scout_client] = lambda: fake
    assert client.get("/api/scout/custom", headers=auth_headers).json() == []
    r = client.post("/api/scout/custom", json={"address": "0x" + "D" * 40}, headers=auth_headers)   # normalized
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["address"] == ADDR_UNKNOWN and body["queued"] is True and body["on_board"] is False
    # idempotent, and an on-board wallet is not queued
    assert client.post("/api/scout/custom", json={"address": ADDR_UNKNOWN}, headers=auth_headers).status_code == 201
    r = client.post("/api/scout/custom", json={"address": ADDR_A}, headers=auth_headers)
    assert r.json()["on_board"] is True and r.json()["queued"] is False
    listed = client.get("/api/scout/custom", headers=auth_headers).json()
    assert [c["address"] for c in listed] == sorted([ADDR_A, ADDR_UNKNOWN])
    assert client.delete(f"/api/scout/custom/{ADDR_UNKNOWN}", headers=auth_headers).status_code == 204
    assert client.delete(f"/api/scout/custom/{ADDR_UNKNOWN}", headers=auth_headers).status_code == 404
    assert client.delete("/api/scout/custom/not-an-address", headers=auth_headers).status_code == 404
    assert [c["address"] for c in client.get("/api/scout/custom", headers=auth_headers).json()] == [ADDR_A]


@pytest.mark.parametrize("bad", ["", "0x123", "0x" + "g" * 40, "vitalik.eth"])
def test_custom_wallet_add_rejects_non_addresses(client: TestClient, auth_headers: dict, bad: str) -> None:
    assert client.post("/api/scout/custom", json={"address": bad}, headers=auth_headers).status_code == 422


def test_custom_wallet_routes_require_auth_and_503_when_scout_missing(client: TestClient, auth_headers: dict, app) -> None:
    assert client.delete(f"/api/scout/custom/{ADDR_A}").status_code == 401
    app.dependency_overrides[get_scout_client] = lambda: UnavailableScoutClient()
    assert client.delete(f"/api/scout/custom/{ADDR_A}", headers=auth_headers).status_code == 503


def test_traders_accepts_the_custom_preset(client: TestClient, auth_headers: dict, app) -> None:
    fake = FakeScoutClient()
    app.dependency_overrides[get_scout_client] = lambda: fake
    assert client.get("/api/scout/traders?preset=custom", headers=auth_headers).status_code == 200
    assert fake.queries[-1]["preset"] == "custom"
    assert client.get("/api/scout/traders?preset=mine", headers=auth_headers).status_code == 422
