"""MCP copy plans (contract v9): POST /api/mcp/plans and .../execute.

Every execute guard with its status, single use, expiry, confirm mismatch
(and burning after 3), his book changing, the caps, the rate limit, the
one-shot flag, the audit log carrying no secret, and enabled/dry_run never
being touched. No HL: the engine preview is FakeEngineClient.preview_result."""
from __future__ import annotations

import json
import os
import stat

import pytest
from api import mcp_plans as mp
from api_fakes import ADDR_A, ADDR_BUILDING, OUR_ADDRESS

TOKEN = "test-token-0123456789abcdef0123456789"   # conftest.TOKEN (conftest is not importable by name)

from contracts.models import (
    MAX_LEADERS,
    Settings,
    WalletPreview,
    WalletPreviewSlice,
)

A = ADDR_A


def slice_(coin="BTC", side="long", his=50_000.0, status="copy", lev=5, reason=None):
    return WalletPreviewSlice(coin=coin, side=side, his_notional_usd=his, weight_pct=50.0,
                              leverage=lev, notional_usd=0.0 if status == "skip" else 40.0,
                              margin_usd=8.0, status=status, reason=reason)


def preview(*slices, addr=A, **kw):
    sl = list(slices) or [slice_(), slice_("ETH", "short", 30_000.0)]
    return WalletPreview(address=addr, as_of_ms=1, allocation_usd=50.0, exposure_mode="match",
                         small_account_mode="concentrate", his_equity_usd=100_000.0,
                         his_gross_notional_usd=sum(s.his_notional_usd for s in sl), slices=sl,
                         copied=sum(s.status != "skip" for s in sl),
                         skipped=sum(s.status == "skip" for s in sl), **kw)


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def plans(app, data_dir, clock):
    st = mp.PlanStore(data_dir, clock=clock)
    app.state.mcp_plan_store = st
    return st


@pytest.fixture
def allow(monkeypatch):
    monkeypatch.setenv(mp.ALLOW_ENV, "1")
    monkeypatch.delenv(mp.MAX_USD_ENV, raising=False)


@pytest.fixture(autouse=True)
def _no_flag_by_default(monkeypatch):
    monkeypatch.delenv(mp.ALLOW_ENV, raising=False)
    monkeypatch.delenv(mp.MAX_USD_ENV, raising=False)


@pytest.fixture
def engine(fake_engine):
    fake_engine.preview_result = preview()
    return fake_engine


def make_plan(client, headers, **body):
    body = {"address": A, "amount_usd": 50.0, **body}
    r = client.post("/api/mcp/plans", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def execute(client, headers, plan, code=None):
    return client.post(f"/api/mcp/plans/{plan['plan_id']}/execute", headers=headers,
                       json={"confirm_code": plan["confirm_code"] if code is None else code})


def audit(data_dir):
    p = data_dir / mp.AUDIT_FILE
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def settings_file(data_dir) -> Settings:
    return Settings(**json.loads((data_dir / "settings.json").read_text()))


# ── plan ─────────────────────────────────────────────────────────────────────

def test_plan_maps_terms_through_the_engine_preview(client, auth_headers, engine, plans):
    p = make_plan(client, auth_headers, amount_usd=75, leverage=7, entry_deviation_pct=1.5,
                  trade_direction="counter", follow=False)
    _, req, _ = engine.preview_calls[-1]
    assert req.settings_source == "custom" and req.allocation_usd == 75.0
    assert req.exposure_mode.value == "target" and req.target_leverage == 7
    assert req.max_worse_entry_pct == 1.5 and req.trade_direction.value == "counter"
    assert req.only_new_positions is False and req.one_shot is True and req.leverage_mode is None
    assert len(p["confirm_code"]) == 6 and p["confirm_code"].isalnum()
    assert p["expires_ms"] - p["created_ms"] == mp.MCP_PLAN_TTL_S * 1000
    assert p["book_summary"] == ["BTC long $50,000", "ETH short $30,000"]
    assert p["trading_live"] is False and p["projection"] is not None


def test_plan_without_leverage_follows_his(client, auth_headers, engine, plans):
    make_plan(client, auth_headers)
    _, req, _ = engine.preview_calls[-1]
    assert req.exposure_mode.value == "match" and req.target_leverage is None
    assert req.leverage_mode.value == "match" and req.one_shot is False
    assert req.max_worse_entry_pct == 2.0 and req.trade_direction.value == "copy"


@pytest.mark.parametrize("body", [
    {"amount_usd": 0}, {"amount_usd": -5}, {"leverage": 0}, {"leverage": 51},
    {"entry_deviation_pct": 50.1}, {"entry_deviation_pct": -1}, {"trade_direction": "both"},
    {"address": "0x123"}, {"extra": 1},
])
def test_plan_validation_422(client, auth_headers, engine, plans, body):
    r = client.post("/api/mcp/plans", headers=auth_headers, json={"address": A, "amount_usd": 50, **body})
    assert r.status_code == 422, r.text


def test_plan_needs_auth(client, engine, plans):
    assert client.post("/api/mcp/plans", json={"address": A, "amount_usd": 5}).status_code == 401
    assert client.post("/api/mcp/plans/x/execute", json={"confirm_code": "x"}).status_code == 401


def test_plan_is_read_only_and_never_touches_the_book(client, auth_headers, engine, plans, data_dir):
    make_plan(client, auth_headers)
    assert not (data_dir / "settings.json").exists()
    st = os.stat(data_dir / mp.PLANS_FILE)
    assert stat.S_IMODE(st.st_mode) == 0o600
    assert stat.S_IMODE(os.stat(data_dir / mp.AUDIT_FILE).st_mode) == 0o600


def test_plan_warnings(client, auth_headers, fake_engine, fake_scout, plans):
    fake_engine.preview_result = preview(
        slice_("BTC", lev=25), slice_("DOGE", his=50.0, status="skip",
                                      reason="copy $0.05 under the $10.5 minimum"),
        min_allocation_for_full_book=5000.0)
    fake_scout.what_if_missing.add(A)
    p = make_plan(client, auth_headers, amount_usd=500, leverage=25, follow=False)
    w = "\n".join(p["warnings"])
    assert "Execution is disabled" in w and "COPYCAT_MCP_ALLOW_TRADING=1" in w
    assert "over the per-plan cap of $100.00" in w
    assert "Trading is not live" in w and "One-shot while trading is off copies nothing" in w
    assert "1 of his 2 positions are under the $10.5 order minimum" in w and "DOGE" in w
    assert "liquidate on roughly a 4.0% adverse move" in w
    assert "No cached 30-day projection" in w and p["projection"] is None
    assert p["executable"] is False


def test_plan_style_and_his_liquidation_warnings(client, auth_headers, engine, fake_scout, plans,
                                                 monkeypatch):
    from api_fakes import make_profile, make_row

    from contracts.models import TradingStyle
    row = make_row(A).model_copy(update={"style": TradingStyle.algo})
    page = fake_scout.page({})
    monkeypatch.setattr(fake_scout, "page", lambda q: page.model_copy(update={"rows": [row]}))
    prof = make_profile(A)
    prof = prof.model_copy(update={"account": prof.account.model_copy(update={"nearest_liq_pct": 3.2})})
    monkeypatch.setattr(fake_scout, "profile", lambda a: prof)
    w = "\n".join(make_plan(client, auth_headers)["warnings"])
    assert "algo/HFT" in w and "His nearest liquidation is 3.2% away" in w


def test_plan_for_a_wallet_already_in_the_book_says_so(client, auth_headers, engine, plans):
    client.post(f"/api/wallets/{A}/copy", headers=auth_headers, json={"allocation_usd": 20})
    client.post(f"/api/wallets/{A}/pause", headers=auth_headers)
    w = "\n".join(make_plan(client, auth_headers)["warnings"])
    assert "already in your book" in w and "keeps it paused" in w


def test_plan_preview_failure_is_502(client, auth_headers, fake_engine, plans):
    from api.engine_client import PreviewFailed
    fake_engine.preview_result = PreviewFailed("his read failed")
    r = client.post("/api/mcp/plans", headers=auth_headers, json={"address": A, "amount_usd": 5})
    assert r.status_code == 502


# ── execute: guards (a)-(f) in order ─────────────────────────────────────────

def test_a_disabled_is_403_with_how_to_enable(client, auth_headers, engine, plans, data_dir):
    p = make_plan(client, auth_headers)
    r = execute(client, auth_headers, p)
    assert r.status_code == 403 and "COPYCAT_MCP_ALLOW_TRADING=1" in r.json()["detail"]
    assert not (data_dir / "settings.json").exists()
    assert audit(data_dir)[-1]["outcome"] == "disabled"


@pytest.mark.parametrize("val", ["", "0", "true", "yes", " 2"])
def test_a_only_exactly_1_enables(monkeypatch, val):
    monkeypatch.setenv(mp.ALLOW_ENV, val)
    assert mp.trading_allowed() is False


def test_execute_writes_custom_terms_and_never_enabled_or_dry_run(client, auth_headers, engine,
                                                                   plans, allow, data_dir):
    client.patch("/api/settings", headers=auth_headers, json={"enabled": True, "dry_run": True})
    before = settings_file(data_dir)
    p = make_plan(client, auth_headers, amount_usd=60, leverage=4, entry_deviation_pct=3)
    r = execute(client, auth_headers, p)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["executed"] is True and out["settings_source"] == "custom" and out["one_shot"] is False
    assert out["trading_live"] is False and "NOT live" in out["note"]
    assert out["wallet"]["address"] == A and out["wallet"]["allocation_usd"] == 60.0
    s = settings_file(data_dir)
    assert (s.enabled, s.dry_run) == (before.enabled, before.dry_run) == (True, True)
    assert A in s.leaders
    o = s.leader_overrides[A]
    assert (o.allocation_usd, o.exposure_mode.value, o.target_leverage, o.max_worse_entry_pct,
            o.trade_direction.value, o.only_new_positions, o.one_shot) == \
        (60.0, "target", 4, 3.0, "copy", False, False)
    assert audit(data_dir)[-1]["outcome"] == "executed"


def test_execute_with_trading_live_says_so(client, auth_headers, engine, plans, allow, data_dir):
    client.patch("/api/settings", headers=auth_headers, json={"enabled": True, "dry_run": False})
    out = execute(client, auth_headers, make_plan(client, auth_headers)).json()
    assert out["trading_live"] is True and "next cycle" in out["note"]
    s = settings_file(data_dir)
    assert s.enabled is True and s.dry_run is False


def test_b_unknown_plan_404(client, auth_headers, engine, plans, allow):
    r = client.post("/api/mcp/plans/plan_nope/execute", headers=auth_headers, json={"confirm_code": "AAAAAA"})
    assert r.status_code == 404


def test_b_single_use_410(client, auth_headers, engine, plans, allow):
    p = make_plan(client, auth_headers)
    assert execute(client, auth_headers, p).status_code == 200
    r = execute(client, auth_headers, p)
    assert r.status_code == 410 and "already used" in r.json()["detail"]


def test_b_expired_410(client, auth_headers, engine, plans, allow, clock, data_dir):
    p = make_plan(client, auth_headers)
    clock.t += mp.MCP_PLAN_TTL_S
    r = execute(client, auth_headers, p)
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert not (data_dir / "settings.json").exists()


def test_expired_plans_are_pruned(client, auth_headers, engine, plans, clock, data_dir):
    old = make_plan(client, auth_headers)
    clock.t += mp.PRUNE_GRACE_S + mp.MCP_PLAN_TTL_S + 1
    make_plan(client, auth_headers)
    stored = json.loads((data_dir / mp.PLANS_FILE).read_text())
    assert old["plan_id"] not in stored and len(stored) == 1


def test_c_confirm_mismatch_403_and_three_burn_the_plan(client, auth_headers, engine, plans, allow,
                                                       data_dir):
    p = make_plan(client, auth_headers)
    for _ in range(2):
        r = execute(client, auth_headers, p, code="ZZZZZZ")
        assert r.status_code == 403 and "does not match" in r.json()["detail"]
    r = execute(client, auth_headers, p, code="ZZZZZZ")
    assert r.status_code == 403 and "void" in r.json()["detail"]
    assert execute(client, auth_headers, p).status_code == 410        # right code, too late
    assert not (data_dir / "settings.json").exists()


def test_c_code_is_case_and_space_tolerant(client, auth_headers, engine, plans, allow):
    p = make_plan(client, auth_headers)
    assert execute(client, auth_headers, p, code=f" {p['confirm_code'].lower()} ").status_code == 200


def test_d_amount_over_cap_403(client, auth_headers, engine, plans, allow, monkeypatch, data_dir):
    p = make_plan(client, auth_headers, amount_usd=100.01)
    r = execute(client, auth_headers, p)
    assert r.status_code == 403 and "cap" in r.json()["detail"]
    monkeypatch.setenv(mp.MAX_USD_ENV, "500")
    p = make_plan(client, auth_headers, amount_usd=400)
    assert execute(client, auth_headers, p).status_code == 200


def test_d_leverage_over_max_position_leverage_403(client, auth_headers, engine, plans, allow):
    client.patch("/api/settings", headers=auth_headers, json={"max_position_leverage": 5})
    p = make_plan(client, auth_headers, leverage=6)
    r = execute(client, auth_headers, p)
    assert r.status_code == 403 and "max_position_leverage" in r.json()["detail"]


def test_e_his_book_changed_409_and_burns(client, auth_headers, fake_engine, plans, allow, data_dir):
    fake_engine.preview_result = preview()
    p = make_plan(client, auth_headers)
    fake_engine.preview_result = preview(slice_(), slice_("ETH", "short", 31_000.0))   # he added
    r = execute(client, auth_headers, p)
    assert r.status_code == 409 and "positions this plan copies changed" in r.json()["detail"]
    fake_engine.preview_result = preview()
    assert execute(client, auth_headers, p).status_code == 410
    assert not (data_dir / "settings.json").exists()


def test_e_mark_moves_do_not_change_the_fingerprint():
    a = [{"coin": "BTC", "side": "long", "notional_usd": 50_000.0},
         {"coin": "ETH", "side": "short", "notional_usd": 30_000.0}]
    b = list(reversed(a))
    assert mp.book_fingerprint(a)[0] == mp.book_fingerprint(b)[0]
    assert mp.book_fingerprint([{**a[0], "notional_usd": 50_000.001}, a[1]])[0] == mp.book_fingerprint(a)[0]
    c = [a[0], {**a[1], "side": "long"}]
    assert mp.book_fingerprint(a)[0] != mp.book_fingerprint(c)[0]
    d = [a[0], {**a[1], "notional_usd": 30_010.0}]
    assert mp.book_fingerprint(a)[0] != mp.book_fingerprint(d)[0]


def test_e_uses_one_account_read_not_a_second_preview(client, auth_headers, fake_engine, plans, allow):
    fake_engine.preview_result = preview()
    p = make_plan(client, auth_headers)
    n = len(fake_engine.preview_calls)
    assert execute(client, auth_headers, p).status_code == 200
    assert len(fake_engine.preview_calls) == n


def test_e_his_read_failing_is_502_and_writes_nothing(client, auth_headers, engine, plans, allow,
                                                     data_dir):
    from api.engine_client import PreviewFailed
    p = make_plan(client, auth_headers)
    engine.book_result = PreviewFailed("read failed")
    assert execute(client, auth_headers, p).status_code == 502
    assert not (data_dir / "settings.json").exists()


def test_f_book_full_409(client, auth_headers, engine, plans, allow, data_dir):
    leaders = ["0x" + f"{i:040x}" for i in range(1, MAX_LEADERS + 1)]
    client.patch("/api/settings", headers=auth_headers, json={"leaders": leaders})
    p = make_plan(client, auth_headers)
    assert p["executable"] is False
    r = execute(client, auth_headers, p)
    assert r.status_code == 409 and "full" in r.json()["detail"]


def test_guards_run_in_order_disabled_before_unknown(client, auth_headers, engine, plans):
    r = client.post("/api/mcp/plans/plan_nope/execute", headers=auth_headers, json={"confirm_code": "A"})
    assert r.status_code == 403          # (a) before (b)


def test_expired_beats_wrong_code(client, auth_headers, engine, plans, allow, clock):
    p = make_plan(client, auth_headers)
    clock.t += 500
    assert execute(client, auth_headers, p, code="ZZZZZZ").status_code == 410    # (b) before (c)


def test_cap_checked_before_book(client, auth_headers, fake_engine, plans, allow):
    fake_engine.preview_result = preview()
    p = make_plan(client, auth_headers, amount_usd=1000)
    fake_engine.preview_result = preview(slice_("SOL"))
    assert execute(client, auth_headers, p).status_code == 403                    # (d) before (e)


def test_own_account_is_400(client, auth_headers, fake_engine, plans, allow):
    fake_engine.preview_result = preview(addr=OUR_ADDRESS)
    p = make_plan(client, auth_headers, address=OUR_ADDRESS)
    assert p["executable"] is False
    assert execute(client, auth_headers, p).status_code == 400


# ── one-shot ─────────────────────────────────────────────────────────────────

def test_follow_false_writes_one_shot_and_follow_true_clears_it(client, auth_headers, engine, plans,
                                                                allow, data_dir):
    out = execute(client, auth_headers, make_plan(client, auth_headers, follow=False)).json()
    assert out["one_shot"] is True and "one-shot" in out["note"]
    assert settings_file(data_dir).leader_overrides[A].one_shot is True
    assert out["wallet"]["one_shot"] is True
    rows = client.get("/api/wallets", headers=auth_headers).json()
    assert next(w for w in rows if w["address"] == A)["one_shot"] is True
    execute(client, auth_headers, make_plan(client, auth_headers, follow=True))
    assert settings_file(data_dir).leader_overrides[A].one_shot is False


def test_web_ticket_repost_keeps_one_shot(client, auth_headers, engine, plans, allow, data_dir):
    execute(client, auth_headers, make_plan(client, auth_headers, follow=False))
    client.post(f"/api/wallets/{A}/copy", headers=auth_headers, json={"allocation_usd": 80})
    assert settings_file(data_dir).leader_overrides[A].one_shot is True


# ── rate limit + audit ───────────────────────────────────────────────────────

def test_rate_limit_10_per_hour(client, auth_headers, engine, plans, allow, clock):
    for _ in range(mp.RATE_LIMIT):
        execute(client, auth_headers, {"plan_id": "plan_nope", "confirm_code": "AAAAAA"})
    r = execute(client, auth_headers, {"plan_id": "plan_nope", "confirm_code": "AAAAAA"})
    assert r.status_code == 429
    clock.t += mp.RATE_WINDOW_S + 1
    assert execute(client, auth_headers, {"plan_id": "plan_nope", "confirm_code": "A"}).status_code == 404


def test_audit_log_has_every_step_and_no_secret(client, auth_headers, engine, plans, allow, data_dir):
    p = make_plan(client, auth_headers)
    execute(client, auth_headers, p, code="WRONG1")
    execute(client, auth_headers, p)
    raw = (data_dir / mp.AUDIT_FILE).read_text()
    assert p["confirm_code"] not in raw and "WRONG1" not in raw and TOKEN not in raw
    assert "confirm_code" not in raw and "Bearer" not in raw
    ev = audit(data_dir)
    assert [(e["event"], e["outcome"]) for e in ev] == [("plan", "created"), ("execute", "bad_code"),
                                                        ("execute", "executed")]
    assert ev[-1]["address"] == A and ev[-1]["amount_usd"] == 50.0


def test_projection_building_address_still_plans(client, auth_headers, fake_engine, plans):
    fake_engine.preview_result = preview(addr=ADDR_BUILDING)
    p = make_plan(client, auth_headers, address=ADDR_BUILDING)
    assert p["request"]["address"] == ADDR_BUILDING


def test_fingerprint_ignores_changes_to_coins_the_plan_does_not_copy():
    from api import mcp_plans as mp
    book = [{"coin": "BTC", "side": "long", "notional_usd": 1000.0},
            {"coin": "DOGE", "side": "short", "notional_usd": 20.0}]
    fp, _ = mp.book_fingerprint(book, ["BTC"])
    churned = [{"coin": "BTC", "side": "long", "notional_usd": 1000.0},
               {"coin": "DOGE", "side": "short", "notional_usd": 55.0},       # he adds to an uncopied coin
               {"coin": "PEPE", "side": "long", "notional_usd": 12.0}]        # and opens another
    assert mp.book_fingerprint(churned, ["BTC"])[0] == fp
    added = [{"coin": "BTC", "side": "long", "notional_usd": 1500.0}]         # a planned coin changed
    assert mp.book_fingerprint(added, ["BTC"])[0] != fp
    closed = [{"coin": "DOGE", "side": "short", "notional_usd": 20.0}]        # a planned coin closed
    assert mp.book_fingerprint(closed, ["BTC"])[0] != fp
