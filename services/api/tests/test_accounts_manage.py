"""/api/accounts management, summary and history routes."""
from __future__ import annotations

import pytest
from eth_account import Account
from test_accounts_onboard import PASS, _clean

from contracts.models import EngineStatus, LeaderStatus


def _connected(client, auth_headers, hlfake, n, label="c"):
    main = Account.from_key("0x" + f"{n:02x}" * 32)
    key = "0x" + f"{n + 1:02x}" * 32
    hlfake.approve(main.address, Account.from_key(key).address)
    r = client.post("/api/accounts/import-key", headers=auth_headers,
                    json={"label": label, "main_address": main.address, "agent_private_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def _created(client, auth_headers, label="Src"):
    r = client.post("/api/accounts/create", json={"label": label, "passphrase": PASS}, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["account"]


def test_activate_rename_delete_and_404(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10, "A")
    r = client.post(f"/api/accounts/{a['id']}/activate", headers=auth_headers)
    assert r.status_code == 200 and r.json()["active"] is True
    r = client.patch(f"/api/accounts/{a['id']}", json={"label": "Renamed"}, headers=auth_headers)
    assert r.json()["label"] == "Renamed"
    assert client.patch(f"/api/accounts/{a['id']}", json={"label": ""}, headers=auth_headers).status_code == 422
    assert client.post("/api/accounts/acc_0000000000000000/activate", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/accounts/{a['id']}", headers=auth_headers).json() == {"ok": True}
    assert client.get("/api/accounts", headers=auth_headers).json() == []
    assert client.delete(f"/api/accounts/{a['id']}", headers=auth_headers).status_code == 404


def test_activate_refuses_to_strand_open_copies_unless_forced(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10, "A")
    b = _connected(client, auth_headers, hlfake, 0x20, "B")
    client.post(f"/api/accounts/{a['id']}/activate", headers=auth_headers)
    backend.engine[a["address"]] = EngineStatus(running=True, enabled=True, dry_run=False, our_address=a["address"],
                                                positions=[{
                                                    "coin": "BTC", "leader": "0x" + "9" * 40, "side": "long",
                                                    "size": 1, "entry_px": 1, "mark_px": 1, "notional_usd": 1,
                                                    "leverage": 1, "is_cross": True, "unrealized_pnl_usd": 0,
                                                    "opened_ms": 1, "sizing_mode": "fixed_margin"}])
    r = client.post(f"/api/accounts/{b['id']}/activate", headers=auth_headers)
    assert r.status_code == 409 and "1 copies open" in r.json()["detail"]
    r = client.post(f"/api/accounts/{b['id']}/activate?force=true", headers=auth_headers)
    assert r.status_code == 200 and r.json()["active"] is True


def test_refresh_agent_statuses(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    r = client.post(f"/api/accounts/{a['id']}/refresh-agent", json={}, headers=auth_headers)
    assert r.status_code == 409 and "re-run sign-in" in r.json()["detail"]
    c = _created(client, auth_headers)
    r = client.post(f"/api/accounts/{c['id']}/refresh-agent", json={"passphrase": "wrong passphrase!"},
                    headers=auth_headers)
    assert r.status_code == 401 and r.json()["detail"] == "invalid passphrase"
    r = client.post(f"/api/accounts/{c['id']}/refresh-agent", json={"passphrase": PASS}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["agent_status"] == "active"


def test_transfer_requires_the_passphrase(client, auth_headers, hlfake, backend, logs):
    src = _created(client, auth_headers)
    dst = _connected(client, auth_headers, hlfake, 0x10)
    body = {"from_account_id": src["id"], "to_address": dst["address"], "amount_usd": 25}
    r = client.post("/api/accounts/transfer", json=body, headers=auth_headers)
    assert r.status_code == 422
    r = client.post("/api/accounts/transfer", json={**body, "passphrase": "not the passphrase"}, headers=auth_headers)
    assert r.status_code == 401 and r.json()["detail"] == "invalid passphrase"
    assert "not the passphrase" not in r.text
    r = client.post("/api/accounts/transfer", json={**body, "passphrase": PASS}, headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"ok": True, "from_address": src["address"],
                                                 "to_address": dst["address"], "amount_usd": 25.0}
    assert hlfake.posts[-1]["action"]["type"] == "usdSend"
    _clean(logs.text, PASS)


def test_summary_balances_exposure_curves_and_copy_margin(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    backend.engine[a["address"]] = EngineStatus(
        running=False, enabled=True, dry_run=False, our_address=a["address"],
        leaders=[LeaderStatus.model_construct(address="0x" + "9" * 40, margin_used_usd=77.5)])
    backend.metrics_v = {"longest_win_streak_days": 4, "avg_hold_h": 3.5}
    r = client.get(f"/api/accounts/{a['id']}/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["balances"] == {"perps_usd": 1000.0, "spot_usd": 75.0, "staked_usd": 100.0, "copytrade_usd": 77.5,
                             "total_usd": 1175.0, "withdrawable_usd": 500.0}
    assert s["unrealized_pnl_usd"] == 10.0 and s["long_notional_usd"] == 900.0 and s["short_notional_usd"] == 300.0
    assert s["account_leverage"] == 1.2 and s["margin_usage_pct"] == 12.0
    assert s["all_time_pnl_usd"] == 150.5 and s["volume_usd"] == 12345.6
    assert s["pnl_curve"]["all"][-1] == {"t_ms": 2, "value": 150.5}
    assert s["longest_win_streak_days"] == 4 and s["avg_hold_h"] == 3.5 and s["style"] is None
    backend.state = None
    assert client.get(f"/api/accounts/{a['id']}/summary", headers=auth_headers).status_code == 502


@pytest.mark.parametrize("kind,check", [
    ("fills", lambda rows: rows[0]["notional_usd"] == 200.0 and rows[0]["side"] == "B"),
    ("orders", lambda rows: rows[0]["status"] == "filled" and rows[0]["coin"] == "BTC"),
    ("transfers", lambda rows: rows[0]["time_ms"] == 7 and rows[0]["delta"]["type"] == "deposit"),
    ("balances", lambda rows: rows[0]["coin"] == "USDC (perps)" and rows[1]["usd_value"] == 50.0),
])
def test_history_kinds(client, auth_headers, hlfake, backend, kind, check):
    a = _connected(client, auth_headers, hlfake, 0x10)
    r = client.get(f"/api/accounts/{a['id']}/history?kind={kind}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["kind"] == kind and check(r.json()["rows"])


def test_history_bad_kind_and_failed_read(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    assert client.get(f"/api/accounts/{a['id']}/history?kind=x", headers=auth_headers).status_code == 422
    backend.fills_v = None
    assert client.get(f"/api/accounts/{a['id']}/history?kind=fills", headers=auth_headers).status_code == 502
