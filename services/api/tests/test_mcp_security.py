"""Audit 2026-10 H2/H3/H5 for the MCP path.

H2: POST /api/mcp/plans never returns the confirm code; only GET
    /api/mcp/plans/pending (admin token) does; the optional macOS notification.
H3: the scoped MCP token reaches exactly api.auth.MCP_SCOPE; every other route
    is 403 for it (checked over EVERY registered route, so a new route is
    denied to the MCP by default).
H5: MCP plans copy with isolated margin; a cumulative cap per UTC day.
"""
from __future__ import annotations

import os
import re
import stat

import pytest
from api import mcp_plans as mp
from api.auth import MCP_SCOPE
from api.config import MCP_TOKEN_FILE, Config
from api_fakes import ADDR_A
from test_mcp_plans import audit, execute, make_plan, settings_file  # noqa: F401 (fixtures below)
from test_mcp_plans import allow, clock, engine, plans  # noqa: F401

from contracts.models import CopyPlanRequest

A = ADDR_A
B = "0x" + "b" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (mp.ALLOW_ENV, mp.MAX_USD_ENV, mp.MAX_USD_DAY_ENV, mp.NOTIFY_ENV):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def mcp_headers(app):
    return {"Authorization": f"Bearer {app.state.config.mcp_token}"}


# ── H2: the code never reaches the caller of POST /plans ──────────────────────

def test_plan_response_has_no_code_and_pending_has_it(client, auth_headers, engine, plans, clock):
    r = client.post("/api/mcp/plans", headers=auth_headers, json={"address": A, "amount_usd": 50})
    body = r.json()
    assert body["confirm_code"] is None
    stored = plans.get(body["plan_id"])[0].confirm_code
    assert stored and re.fullmatch(r"[A-Z2-9]{6}", stored)
    assert stored not in r.text
    pend = client.get("/api/mcp/plans/pending", headers=auth_headers).json()
    assert [(p["plan_id"], p["confirm_code"], p["amount_usd"], p["address"]) for p in pend] == \
        [(body["plan_id"], stored, 50.0, A)]
    clock.t += mp.MCP_PLAN_TTL_S + 1                 # expired plans leave the list
    assert client.get("/api/mcp/plans/pending", headers=auth_headers).json() == []


def test_used_plans_leave_the_pending_list(client, auth_headers, engine, plans, allow):
    p = make_plan(client, auth_headers)
    assert execute(client, auth_headers, p).status_code == 200
    assert client.get("/api/mcp/plans/pending", headers=auth_headers).json() == []


def test_a_plan_with_no_stored_code_cannot_execute(client, auth_headers, engine, plans, allow):
    p = make_plan(client, auth_headers)
    plan, bad = plans.get(p["plan_id"])
    with plans.locked():
        plans.update(plan.model_copy(update={"confirm_code": None}), bad)
    assert execute(client, auth_headers, p).status_code == 403


def test_notify_is_opt_in_darwin_only_and_carries_only_safe_fields(client, auth_headers, engine, plans):
    p = make_plan(client, auth_headers)
    plan = plans.get(p["plan_id"])[0]
    calls = []
    run = lambda args, **kw: calls.append(args)          # noqa: E731
    assert mp.notify(plan, environ={}, run=run, platform="darwin") is False
    assert mp.notify(plan, environ={mp.NOTIFY_ENV: "1"}, run=run, platform="linux") is False
    assert calls == []
    assert mp.notify(plan, environ={mp.NOTIFY_ENV: "1"}, run=run, platform="darwin") is True
    (args,) = calls
    assert args[0] == "osascript" and args[1] == "-e" and plan.confirm_code in args[2]
    assert args[2].count('"') == 6                        # the three quoted literals only

    def boom(*a, **k):
        raise OSError("no osascript")
    assert mp.notify(plan, environ={mp.NOTIFY_ENV: "1"}, run=boom, platform="darwin") is False


def test_create_notifies_only_executable_plans(client, auth_headers, engine, plans, allow, monkeypatch):
    sent = []
    monkeypatch.setattr(mp, "notify", lambda plan: sent.append(plan.plan_id))
    p = make_plan(client, auth_headers)
    assert sent == [p["plan_id"]]
    make_plan(client, auth_headers, amount_usd=500)       # over the cap: not executable
    assert sent == [p["plan_id"]]


# ── H3: scoped MCP token ──────────────────────────────────────────────────────

def test_mcp_token_file_is_generated_0600_and_differs_from_admin(app, data_dir):
    path = data_dir / MCP_TOKEN_FILE
    assert path.exists() and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    tok = path.read_text().strip()
    assert tok == app.state.config.mcp_token and tok != app.state.config.api_token and len(tok) >= 32


def test_mcp_token_equal_to_admin_refuses_to_start(data_dir):
    t = "x" * 40
    with pytest.raises(RuntimeError, match="MCP token equals"):
        Config(data_dir=data_dir, api_token=t, mcp_token=t).validate_or_raise()


def _concrete(path: str) -> str:
    return (path.replace("{address}", A).replace("{plan_id}", "plan_0123456789abcdef")
            .replace("{account_id}", "acc_0000000000000000").replace("{run_id}", "r1"))


def _all_routes(app):
    """(METHOD, template) of every api route, from the OpenAPI schema (FastAPI nests
    included routers, so app.routes is not flat). test_openapi pins the schema to the app."""
    return {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops}


def test_every_route_outside_the_scope_is_403_for_the_mcp_token(app, client, mcp_headers):
    checked = 0
    for method, path in sorted(_all_routes(app)):
        if path == "/api/health":
            continue
        if (method, path) not in MCP_SCOPE:
            r = client.request(method, _concrete(path), headers=mcp_headers, json={})
            assert r.status_code == 403, (method, path, r.status_code, r.text)
            assert "MCP token" in r.json()["detail"]
            checked += 1
    assert checked >= 30


def test_every_scope_entry_is_a_real_route(app):
    real = _all_routes(app)
    assert MCP_SCOPE <= real, MCP_SCOPE - real


def test_mcp_token_cannot_read_codes_or_flip_switches(client, mcp_headers, auth_headers, engine, plans):
    for method, path, body in [
        ("GET", "/api/mcp/plans/pending", None),
        ("PATCH", "/api/settings", {"enabled": True, "dry_run": False}),
        ("PUT", "/api/settings", {}),
        ("POST", "/api/leaders", {"address": A}),
        ("POST", f"/api/wallets/{A}/copy", {"allocation_usd": 1000}),
        ("POST", "/api/engine/close-all", {}),
        ("GET", "/api/accounts", None),
    ]:
        assert client.request(method, path, headers=mcp_headers, json=body).status_code == 403, path
    s = client.get("/api/settings", headers=auth_headers).json()
    assert s["enabled"] is False and s["leaders"] == []


def test_mcp_token_reaches_its_scope(client, mcp_headers, engine, plans, allow):
    assert client.get("/api/settings", headers=mcp_headers).status_code == 200
    assert client.get("/api/status", headers=mcp_headers).status_code in (200, 503)
    assert client.get("/api/wallets", headers=mcp_headers).status_code == 200
    assert client.get("/api/scout/sim-terms", headers=mcp_headers).status_code in (200, 503)
    assert client.put("/api/scout/sim-terms", headers=mcp_headers, json={}).status_code == 403
    r = client.post("/api/mcp/plans", headers=mcp_headers, json={"address": A, "amount_usd": 50})
    assert r.status_code == 200 and r.json()["confirm_code"] is None
    r2 = client.post(f"/api/mcp/plans/{r.json()['plan_id']}/execute", headers=mcp_headers,
                     json={"confirm_code": "WRONG2"})
    assert r2.status_code == 403 and "does not match" in r2.json()["detail"]


def test_path_tricks_do_not_widen_the_scope(client, mcp_headers):
    for path in ["/api/scout/../settings", "/api/scout/traders/%2E%2E/%2E%2E/settings",
                 "/api/settings/", "/api//settings"]:
        r = client.patch(path, headers=mcp_headers, json={"enabled": True})
        assert r.status_code in (403, 404, 405, 307), (path, r.status_code)


def test_bad_tokens_still_401(client):
    assert client.get("/api/settings", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/settings", headers={"Authorization": "Bearer caf\u00e9".encode("latin-1")}).status_code == 401


# ── H5: isolated margin + daily cap ───────────────────────────────────────────

def test_plans_always_copy_isolated(client, auth_headers, engine, plans, allow, data_dir):
    client.patch("/api/settings", headers=auth_headers, json={"margin_mode": "cross"})
    creq = mp.copy_request_for(CopyPlanRequest(address=A, amount_usd=50))
    assert creq.margin_mode.value == "isolated"
    p = make_plan(client, auth_headers)
    assert p["copy_request"]["margin_mode"] == "isolated"
    assert any("Isolated margin" in w for w in p["warnings"])
    assert execute(client, auth_headers, p).status_code == 200
    s = settings_file(data_dir)
    assert s.margin_mode.value == "cross"                           # global untouched
    assert s.leader_overrides[A].margin_mode.value == "isolated"
    assert s.for_leader(A).margin_mode.value == "isolated"


def test_daily_cap_sums_executed_plans_per_utc_day(client, auth_headers, engine, plans, allow,
                                                   clock, monkeypatch, data_dir):
    clock.t = 1_700_006_400.0          # 2023-11-15 00:00 UTC
    assert mp.max_usd_per_day({}) == mp.DEFAULT_MAX_USD
    assert mp.max_usd_per_day({mp.MAX_USD_ENV: "70"}) == 70.0
    assert mp.max_usd_per_day({mp.MAX_USD_DAY_ENV: "junk", mp.MAX_USD_ENV: "70"}) == 70.0
    monkeypatch.setenv(mp.MAX_USD_DAY_ENV, "150")
    assert execute(client, auth_headers, make_plan(client, auth_headers, amount_usd=60)).status_code == 200
    assert execute(client, auth_headers, make_plan(client, auth_headers, address=B,
                                                   amount_usd=80)).status_code == 200
    assert plans.executed_usd_today() == 140.0
    p = make_plan(client, auth_headers, amount_usd=20)
    assert p["executable"] is False and any("daily cap" in w for w in p["warnings"])
    r = execute(client, auth_headers, p)
    assert r.status_code == 403 and "daily cap" in r.json()["detail"]
    assert audit(data_dir)[-1]["outcome"] == "over_day_cap"
    assert execute(client, auth_headers, make_plan(client, auth_headers, amount_usd=10)).status_code == 200
    clock.t += 86_400                  # next UTC day: the budget resets
    assert plans.executed_usd_today() == 0.0
    assert execute(client, auth_headers, make_plan(client, auth_headers, amount_usd=100)).status_code == 200


def test_daily_cap_defaults_to_the_per_plan_cap(client, auth_headers, engine, plans, allow):
    assert execute(client, auth_headers, make_plan(client, auth_headers, amount_usd=60)).status_code == 200
    r = execute(client, auth_headers, make_plan(client, auth_headers, address=B, amount_usd=60))
    assert r.status_code == 403 and "daily cap" in r.json()["detail"]
