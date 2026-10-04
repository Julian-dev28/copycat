"""Trade page routes: /api/wallets (copy, preview, stop, list)."""
from __future__ import annotations

import json

from api.deps import get_engine_client
from api.engine_client import PreviewFailed
from api_fakes import OUR_ADDRESS, FakeEngineClient, UnavailableEngineClient
from fastapi.testclient import TestClient

from contracts.models import (
    MAX_LEADERS,
    EngineStatus,
    ExposureMode,
    LeaderStatus,
    Settings,
    SmallAccountMode,
    WalletPreview,
)

A = "0x" + "a" * 40
B = "0x" + "b" * 40


def copy(client, headers, addr=A, **body):
    body.setdefault("allocation_usd", 1000.0)
    return client.post(f"/api/wallets/{addr}/copy", headers=headers, json=body)


# ── copy ────────────────────────────────────────────────────────────────────

def test_copy_adds_the_wallet_with_allocation_terms(client, auth_headers):
    r = copy(client, auth_headers, exposure_mode="target", target_leverage=5,
             margin_mode="cross", max_worse_entry_pct=3.0, small_account_mode="bump")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["leaders"] == [A]
    o = s["leader_overrides"][A]
    assert (o["sizing_mode"], o["allocation_usd"], o["exposure_mode"], o["target_leverage"],
            o["margin_mode"], o["max_worse_entry_pct"], o["small_account_mode"]) == (
        "allocation", 1000.0, "target", 5, "cross", 3.0, "bump")
    assert isinstance(o["invested_ms"], int) and o["invested_ms"] > 0


def test_repost_adjusts_and_keeps_invested_ms(client, auth_headers):
    first = copy(client, auth_headers).json()["leader_overrides"][A]["invested_ms"]
    r = copy(client, auth_headers, allocation_usd=2500.0)
    o = r.json()["leader_overrides"][A]
    assert o["allocation_usd"] == 2500.0 and o["invested_ms"] == first
    assert r.json()["leaders"] == [A]


def test_switching_a_wallet_to_allocation_starts_a_fresh_investment(client, auth_headers):
    client.post("/api/leaders", headers=auth_headers, json={"address": A})
    client.patch("/api/settings", headers=auth_headers,
                 json={"leader_overrides": {A: {"leverage_mode": "fixed", "leverage": 7}}})
    o = copy(client, auth_headers).json()["leader_overrides"][A]
    assert o["invested_ms"] and o["leverage_mode"] == "fixed" and o["leverage"] == 7


def test_target_without_leverage_is_422(client, auth_headers):
    assert copy(client, auth_headers, exposure_mode="target").status_code == 422
    assert copy(client, auth_headers, allocation_usd=0).status_code == 422
    assert copy(client, auth_headers, bogus=1).status_code == 422


def test_copy_409_at_the_cap_and_400_for_bad_or_own_address(client, auth_headers):
    for i in range(MAX_LEADERS):
        assert copy(client, auth_headers, addr="0x" + f"{i + 1:040x}").status_code == 200
    assert copy(client, auth_headers, addr=B).status_code == 409
    assert copy(client, auth_headers, addr="0x" + "1" * 39).status_code == 400
    r = copy(client, auth_headers, addr=OUR_ADDRESS)
    assert r.status_code == 400 and "own account" in r.json()["detail"]


def test_copy_cancels_a_pending_stop(client, auth_headers, data_dir):
    copy(client, auth_headers)
    client.post(f"/api/wallets/{A}/stop", headers=auth_headers, json={"close_positions": True})
    assert (data_dir / "stop" / f"{A}.flag").exists()
    copy(client, auth_headers)
    assert not (data_dir / "stop" / f"{A}.flag").exists()


# ── stop ────────────────────────────────────────────────────────────────────

def test_stop_removes_the_wallet_and_writes_the_flag(client, auth_headers, data_dir):
    copy(client, auth_headers)
    r = client.post(f"/api/wallets/{A}/stop", headers=auth_headers, json={"close_positions": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stopping"] is True
    assert A not in body["settings"]["leaders"] and A not in body["settings"]["leader_overrides"]
    flag = json.loads((data_dir / "stop" / f"{A}.flag").read_text())
    assert flag["close_positions"] is True and flag["requested_ms"] > 0


def test_stop_without_close_is_not_stopping(client, auth_headers, data_dir):
    copy(client, auth_headers)
    r = client.post(f"/api/wallets/{A}/stop", headers=auth_headers, json={"close_positions": False})
    assert r.json()["stopping"] is False
    assert json.loads((data_dir / "stop" / f"{A}.flag").read_text())["close_positions"] is False


def _orphan(fake_engine: FakeEngineClient, addr: str, copies: int) -> None:
    fake_engine._status = EngineStatus(running=True, enabled=True, dry_run=False, leaders=[
        LeaderStatus(address=addr, read_ok=True, effective=Settings(), open_copies=copies,
                     owned_coins=["BTC"] if copies else [])])


def test_stop_404_unless_in_book_or_orphan_with_copies(client, auth_headers, fake_engine):
    r = client.post(f"/api/wallets/{B}/stop", headers=auth_headers, json={})
    assert r.status_code == 404
    _orphan(fake_engine, B, 0)
    assert client.post(f"/api/wallets/{B}/stop", headers=auth_headers, json={}).status_code == 404
    _orphan(fake_engine, B, 1)
    assert client.post(f"/api/wallets/{B}/stop", headers=auth_headers, json={}).status_code == 200


def test_stop_503_when_orphan_check_impossible(client, auth_headers, app):
    app.dependency_overrides[get_engine_client] = lambda: UnavailableEngineClient()
    assert client.post(f"/api/wallets/{B}/stop", headers=auth_headers, json={}).status_code == 503


# ── list ────────────────────────────────────────────────────────────────────

def test_wallets_rows_and_roe(client, auth_headers, fake_engine):
    copy(client, auth_headers, allocation_usd=500.0, exposure_mode="target", target_leverage=4)
    winding = Settings(sizing_mode="allocation", allocation_usd=200.0, exposure_mode="match")
    fake_engine._status = EngineStatus(running=True, enabled=True, dry_run=False, leaders=[
        LeaderStatus(address=A, read_ok=True, equity_usd=1e6, effective=Settings(), open_copies=2,
                     owned_coins=["BTC", "ETH"], margin_used_usd=480.0, exposure_usd=1920.0,
                     unrealized_pnl_usd=30.0, realized_pnl_usd=-5.0, fees_usd=1.0),
        LeaderStatus(address=B, read_ok=True, effective=winding, open_copies=1, owned_coins=["SOL"],
                     unrealized_pnl_usd=-10.0, stopping=True),
        LeaderStatus(address="0x" + "c" * 40, read_ok=True, effective=Settings()),   # long gone
    ])
    r = client.get("/api/wallets", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert [x["address"] for x in rows] == [A, B]
    a, b = rows
    # (-5 + 30) / 500 = 5%
    assert (a["in_book"], a["pnl_usd"], a["roe_pct"], a["allocation_usd"], a["target_leverage"]) == (
        True, 25.0, 5.0, 500.0, 4)
    assert a["exposure_mode"] == "target" and a["open_copies"] == 2 and a["invested_ms"]
    # -10 / 200 = -5%, terms from the engine's effective
    assert (b["in_book"], b["stopping"], b["roe_pct"], b["exposure_mode"]) == (False, True, -5.0, "match")


def test_wallets_without_engine_still_lists_the_book(client, auth_headers, app):
    copy(client, auth_headers)
    app.dependency_overrides[get_engine_client] = lambda: UnavailableEngineClient()
    rows = client.get("/api/wallets", headers=auth_headers).json()
    assert [(x["address"], x["read_ok"], x["roe_pct"]) for x in rows] == [(A, False, 0.0)]


def test_non_allocation_wallet_has_no_roe(client, auth_headers):
    client.post("/api/leaders", headers=auth_headers, json={"address": A})
    row = client.get("/api/wallets", headers=auth_headers).json()[0]
    assert row["roe_pct"] is None and row["allocation_usd"] is None


# ── preview ─────────────────────────────────────────────────────────────────

def test_preview_passes_the_ticket_and_current_settings(client, auth_headers, fake_engine):
    fake_engine.preview_result = WalletPreview(
        address=A, as_of_ms=1, allocation_usd=20.0, exposure_mode=ExposureMode.target,
        target_leverage=5, small_account_mode=SmallAccountMode.concentrate, his_equity_usd=1e6,
        his_gross_notional_usd=1e6, copied=4, skipped=11, min_allocation_for_full_book=420.0)
    r = client.post(f"/api/wallets/{A}/preview", headers=auth_headers,
                    json={"allocation_usd": 20, "exposure_mode": "target", "target_leverage": 5})
    assert r.status_code == 200, r.text
    assert r.json()["copied"] == 4 and r.json()["min_allocation_for_full_book"] == 420.0
    addr, req, settings = fake_engine.preview_calls[0]
    assert addr == A and req.allocation_usd == 20 and isinstance(settings, Settings)


def test_preview_errors(client, auth_headers, fake_engine, app):
    url = f"/api/wallets/{A}/preview"
    assert client.post(url, headers=auth_headers, json={"allocation_usd": 20,
                                                        "exposure_mode": "target"}).status_code == 422
    assert client.post("/api/wallets/nope/preview", headers=auth_headers,
                       json={"allocation_usd": 20}).status_code == 400
    fake_engine.preview_result = PreviewFailed("account read failed")
    assert client.post(url, headers=auth_headers, json={"allocation_usd": 20}).status_code == 502
    app.dependency_overrides[get_engine_client] = lambda: UnavailableEngineClient()
    assert client.post(url, headers=auth_headers, json={"allocation_usd": 20}).status_code == 503


# ── auth ────────────────────────────────────────────────────────────────────

def test_every_wallet_route_requires_auth(client: TestClient):
    assert client.get("/api/wallets").status_code == 401
    for action in ("copy", "preview", "stop"):
        r = client.post(f"/api/wallets/{A}/{action}", json={"allocation_usd": 10})
        assert r.status_code == 401, action


# ── v7: settings_source global | custom ─────────────────────────────────────

def test_global_copy_adds_the_wallet_with_no_terms(client, auth_headers):
    r = client.post(f"/api/wallets/{A}/copy", headers=auth_headers,
                    json={"settings_source": "global"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["leaders"] == [A]
    o = s["leader_overrides"][A]
    # bookkeeping only: invested_ms for the PnL ledger, nothing that sizes
    assert isinstance(o["invested_ms"], int)
    assert {k for k, v in o.items() if v is not None} == {"invested_ms"}
    row = client.get("/api/wallets", headers=auth_headers).json()[0]
    assert row["settings_source"] == "global" and row["roe_pct"] is None


def test_global_copy_clears_an_existing_custom_override_and_keeps_invested_ms(client, auth_headers):
    first = copy(client, auth_headers, leverage_mode="fixed", leverage=3).json()
    inv = first["leader_overrides"][A]["invested_ms"]
    s = client.post(f"/api/wallets/{A}/copy", headers=auth_headers,
                    json={"settings_source": "global", "allocation_usd": 50}).json()
    assert s["leader_overrides"][A] == {**{k: None for k in s["leader_overrides"][A]},
                                        "invested_ms": inv}


def test_global_to_custom_keeps_the_investment(client, auth_headers):
    inv = client.post(f"/api/wallets/{A}/copy", headers=auth_headers,
                      json={"settings_source": "global"}).json()["leader_overrides"][A]["invested_ms"]
    o = copy(client, auth_headers).json()["leader_overrides"][A]
    assert o["invested_ms"] == inv and o["sizing_mode"] == "allocation"


def test_custom_writes_leverage_and_only_new_positions(client, auth_headers):
    o = copy(client, auth_headers, leverage_mode="fixed", leverage=7,
             only_new_positions=True).json()["leader_overrides"][A]
    assert (o["leverage_mode"], o["leverage"], o["only_new_positions"]) == ("fixed", 7, True)
    row = client.get("/api/wallets", headers=auth_headers).json()[0]
    assert row["settings_source"] == "custom"


def test_custom_without_allocation_is_422(client, auth_headers):
    r = client.post(f"/api/wallets/{A}/copy", headers=auth_headers, json={"settings_source": "custom"})
    assert r.status_code == 422
    r = client.post(f"/api/wallets/{A}/copy", headers=auth_headers, json={})
    assert r.status_code == 422                                     # custom is the default


def test_global_copy_409_and_400(client, auth_headers):
    for i in range(MAX_LEADERS):
        client.post(f"/api/wallets/{'0x' + f'{i + 1:040x}'}/copy", headers=auth_headers,
                    json={"settings_source": "global"})
    r = client.post(f"/api/wallets/{B}/copy", headers=auth_headers, json={"settings_source": "global"})
    assert r.status_code == 409
    r = client.post(f"/api/wallets/{OUR_ADDRESS}/copy", headers=auth_headers,
                    json={"settings_source": "global"})
    assert r.status_code == 400


def test_wallet_added_by_hand_is_global(client, auth_headers):
    client.post("/api/leaders", headers=auth_headers, json={"address": A})
    assert client.get("/api/wallets", headers=auth_headers).json()[0]["settings_source"] == "global"


def test_winding_down_source_follows_the_terms_it_ran_with(client, auth_headers, fake_engine):
    ran_custom = Settings(sizing_mode="allocation", allocation_usd=100.0, invested_ms=5)
    fake_engine._status = EngineStatus(running=True, enabled=True, dry_run=False, leaders=[
        LeaderStatus(address=A, read_ok=True, effective=ran_custom, open_copies=1),
        LeaderStatus(address=B, read_ok=True, effective=Settings(), open_copies=1)])
    rows = {r["address"]: r for r in client.get("/api/wallets", headers=auth_headers).json()}
    assert rows[A]["settings_source"] == "custom" and rows[B]["settings_source"] == "global"


def test_preview_global_needs_no_allocation(client, auth_headers, fake_engine):
    fake_engine.preview_result = WalletPreview(
        address=A, as_of_ms=1, allocation_usd=0.0, exposure_mode=ExposureMode.match,
        small_account_mode=SmallAccountMode.concentrate, his_equity_usd=1.0,
        his_gross_notional_usd=1.0)
    r = client.post(f"/api/wallets/{A}/preview", headers=auth_headers,
                    json={"settings_source": "global"})
    assert r.status_code == 200, r.text
    assert fake_engine.preview_calls[0][1].settings_source == "global"
