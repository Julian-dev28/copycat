"""/api/accounts/{id}/funding-info and the money actions (prepare/submit/run).

Real vault in a temp dir, fake Hyperliquid (accounts_fakes.FakeHL) and canned
reads (FakeBackend: perps withdrawable 400, spot USDC 50). Nothing is sent anywhere.
"""
from __future__ import annotations

from eth_account import Account
from test_accounts_manage import _connected, _created
from test_accounts_onboard import PASS, _clean

OUTSIDE = "0x" + "99" * 20


def _sign(td, n) -> str:
    key = Account.from_key("0x" + f"{n:02x}" * 32).key
    return "0x" + bytes(Account.sign_typed_data(key, full_message=td).signature).hex()


def _prepare(client, h, acct_id, **body):
    return client.post(f"/api/accounts/{acct_id}/action/prepare", json=body, headers=h)


def test_funding_info_has_the_verified_bridge_facts_and_live_limits(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    r = client.get(f"/api/accounts/{a['id']}/funding-info", headers=auth_headers)
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["network"] == "mainnet" and f["chain_id"] == 42161
    assert f["usdc_address"] == "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    assert f["bridge_address"].lower() == "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
    assert f["min_deposit_usd"] == 5.0 and f["withdraw_fee_usd"] == 1.0
    assert f["account_address"] == a["address"] and f["signer"] == "browser"
    assert f["limits"] == {"abstraction": "default", "unified": False, "perps_withdrawable_usd": 400.0,
                           "spot_usdc_free_usd": 50.0}
    assert any("lost" in n for n in f["notes"])
    c = _created(client, auth_headers)
    assert client.get(f"/api/accounts/{c['id']}/funding-info", headers=auth_headers).json()["signer"] == "passphrase"
    backend.state = None                                       # a failed read: facts still, limits null
    r = client.get(f"/api/accounts/{a['id']}/funding-info", headers=auth_headers)
    assert r.status_code == 200 and r.json()["limits"] is None


def test_testnet_funding_info(client, auth_headers, hlfake, backend, monkeypatch):
    a = _connected(client, auth_headers, hlfake, 0x10)
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    f = client.get(f"/api/accounts/{a['id']}/funding-info", headers=auth_headers).json()
    assert f["chain_id"] == 421614 and f["usdc_address"] == "0x1baAbB04529D43a73232B713C0FE471f7c7334d5"
    assert f["bridge_address"] == "0x08cfc1B6b2dCF36A1480b99353A354AA8AC56f89"


def test_unified_account_reports_it_and_refuses_a_move(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    backend.state = {**backend.state, "abstraction": "unifiedAccount", "available": {"": 50.0}}
    f = client.get(f"/api/accounts/{a['id']}/funding-info", headers=auth_headers).json()
    assert f["limits"]["unified"] is True and any("Unified" in n for n in f["notes"])
    r = _prepare(client, auth_headers, a["id"], kind="usd_class_transfer", amount_usd=5, to_perp=True)
    assert r.status_code == 400 and "unified" in r.json()["detail"]


def test_browser_withdraw_round_trip(client, auth_headers, hlfake, backend, data_dir):
    a = _connected(client, auth_headers, hlfake, 0x10)
    r = _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=25)
    assert r.status_code == 200, r.text
    prep = r.json()
    assert prep["action"]["destination"] == a["address"] and prep["typed_data"]["domain"]["chainId"] == 42161
    sig = _sign(prep["typed_data"], 0x10)
    r = client.post(f"/api/accounts/{a['id']}/action/submit", headers=auth_headers,
                    json={"kind": "withdraw", "action": prep["action"], "nonce": prep["nonce"], "signature": sig})
    assert r.status_code == 200, r.text
    assert r.json()["fee_usd"] == 1.0 and r.json()["destination"] == a["address"]
    assert hlfake.posts[-1]["action"] == prep["action"]
    _clean((data_dir / "vault" / "audit.jsonl").read_text(), sig[2:66], sig[66:130])


def test_signer_mismatch_and_bounds_over_http(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    prep = _prepare(client, auth_headers, a["id"], kind="usd_class_transfer", amount_usd=10, to_perp=False).json()
    n = len(hlfake.posts)
    r = client.post(f"/api/accounts/{a['id']}/action/submit", headers=auth_headers,
                    json={"kind": "usd_class_transfer", "action": prep["action"], "nonce": prep["nonce"],
                          "signature": _sign(prep["typed_data"], 0x30)})
    assert r.status_code == 400 and "not made by" in r.json()["detail"]
    assert len(hlfake.posts) == n
    # spot -> perps is capped by spot USDC free (50), perps -> spot by withdrawable (400)
    assert _prepare(client, auth_headers, a["id"], kind="usd_class_transfer", amount_usd=60, to_perp=True).status_code == 400
    assert _prepare(client, auth_headers, a["id"], kind="usd_class_transfer", amount_usd=60, to_perp=False).status_code == 200
    assert _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=400.01).status_code == 400
    assert _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=0).status_code == 422
    assert _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=5, destination=OUTSIDE).status_code == 400
    assert _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=5, destination=OUTSIDE,
                    confirm_destination=OUTSIDE).status_code == 200
    backend.state = None
    assert _prepare(client, auth_headers, a["id"], kind="withdraw", amount_usd=5).status_code == 502


def test_passphrase_route_and_rate_limit(client, auth_headers, hlfake, backend, logs, data_dir):
    c = _created(client, auth_headers)
    url = f"/api/accounts/{c['id']}/action"
    body = {"kind": "withdraw", "amount_usd": 5, "passphrase": "not the passphrase"}
    r = client.post(url, json=body, headers=auth_headers)
    assert r.status_code == 401 and "not the passphrase" not in r.text
    r = client.post(url, json={**body, "passphrase": PASS}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["destination"] == c["address"] and hlfake.posts[-1]["action"]["type"] == "withdraw3"
    for _ in range(3):
        client.post(url, json={**body, "passphrase": PASS}, headers=auth_headers)
    assert client.post(url, json={**body, "passphrase": PASS}, headers=auth_headers).status_code == 429
    # another kind has its own bucket
    r = client.post(url, json={"kind": "usd_class_transfer", "amount_usd": 1, "to_perp": True, "passphrase": PASS},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    _clean(logs.text, PASS, "not the passphrase")
    _clean((data_dir / "vault" / "audit.jsonl").read_text(), PASS, "not the passphrase")


def test_browser_submit_is_rate_limited(client, auth_headers, hlfake, backend):
    a = _connected(client, auth_headers, hlfake, 0x10)
    body = {"kind": "usd_send", "action": {}, "nonce": 1, "signature": "0x00"}
    codes = [client.post(f"/api/accounts/{a['id']}/action/submit", json=body, headers=auth_headers).status_code
             for _ in range(6)]
    assert codes == [400] * 5 + [429]


def test_validation_errors_never_echo_the_passphrase(client, auth_headers, hlfake, backend):
    c = _created(client, auth_headers)
    r = client.post(f"/api/accounts/{c['id']}/action", headers=auth_headers,
                    json={"kind": "teleport", "amount_usd": 5, "passphrase": "super secret words"})
    assert r.status_code == 422 and "super secret words" not in r.text
