"""/api/accounts onboarding routes. Every test also asserts that no secret
reaches a response it should not, or any log line."""
from __future__ import annotations

from eth_account import Account

PASS = "correct horse battery staple"
MAIN = Account.from_key("0x" + "11" * 32)
AGENT_KEY = "0x" + "22" * 32
AGENT = Account.from_key(AGENT_KEY)


def _clean(text: str, *secrets: str) -> None:
    for s in secrets:
        assert s.removeprefix("0x") not in text, "secret leaked"


def test_routes_require_auth(client, hlfake, backend):
    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/accounts/create", json={"label": "x", "passphrase": PASS}).status_code == 401


def test_create_returns_the_key_once_and_never_again(client, auth_headers, hlfake, backend, logs, data_dir):
    r = client.post("/api/accounts/create", json={"label": "Fresh", "passphrase": PASS}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    key = body["private_key"]
    assert Account.from_key(key).address.lower() == body["account"]["address"]
    assert body["account"]["has_main_key"] and "shown once" in body["backup_warning"]
    listed = client.get("/api/accounts", headers=auth_headers)
    assert listed.status_code == 200 and [a["id"] for a in listed.json()] == [body["account"]["id"]]
    _clean(listed.text, key)
    _clean(logs.text, key, PASS)
    for p in (data_dir / "vault").rglob("*"):
        if p.is_file():
            _clean(p.read_text(errors="ignore"), key, PASS)


def test_validation_errors_never_echo_the_secret(client, auth_headers, hlfake, backend):
    r = client.post("/api/accounts/create", json={"label": "x", "passphrase": "short-pw"}, headers=auth_headers)
    assert r.status_code == 422 and "short-pw" not in r.text
    r = client.post("/api/accounts/import-key", json={"label": "x", "main_address": MAIN.address,
                                                      "agent_private_key": AGENT_KEY, "extra": 1},
                    headers=auth_headers)
    assert r.status_code == 422
    _clean(r.text, AGENT_KEY)


def test_import_key_refuses_the_main_key_and_accepts_an_approved_agent(client, auth_headers, hlfake, backend, logs):
    main_key = "0x" + "11" * 32
    r = client.post("/api/accounts/import-key", json={"label": "x", "main_address": MAIN.address,
                                                      "agent_private_key": main_key}, headers=auth_headers)
    assert r.status_code == 400 and "main wallet" in r.json()["detail"]
    _clean(r.text, main_key)
    r = client.post("/api/accounts/import-key", json={"label": "Bot", "main_address": MAIN.address,
                                                      "agent_private_key": AGENT_KEY}, headers=auth_headers)
    assert r.status_code == 400 and "not an approved API wallet" in r.json()["detail"]
    hlfake.approve(MAIN.address, AGENT.address)
    r = client.post("/api/accounts/import-key", json={"label": "Bot", "main_address": MAIN.address,
                                                      "agent_private_key": AGENT_KEY}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["kind"] == "connected_key"
    assert r.json()["agent_address"] == AGENT.address.lower()
    _clean(r.text, AGENT_KEY)
    _clean(logs.text, AGENT_KEY, main_key)


def test_browser_sign_in_prepare_then_submit(client, auth_headers, hlfake, backend, logs):
    r = client.post("/api/accounts/approve/prepare", json={"main_address": MAIN.address,
                                                           "agent_address": AGENT.address}, headers=auth_headers)
    assert r.status_code == 200, r.text
    prep = r.json()
    other = Account.from_key("0x" + "33" * 32)
    for signer, expect in ((other, 400), (MAIN, 200)):
        sig = Account.sign_typed_data(signer.key, full_message=prep["typed_data"]).signature.hex()
        r = client.post("/api/accounts/approve/submit", headers=auth_headers, json={
            "label": "Ledger", "main_address": MAIN.address, "agent_private_key": AGENT_KEY,
            "action": prep["action"], "nonce": prep["nonce"], "signature": "0x" + sig.removeprefix("0x")})
        assert r.status_code == expect, r.text
    assert r.json()["kind"] == "connected_signed" and r.json()["agent_status"] == "active"
    _clean(r.text, AGENT_KEY)
    _clean(logs.text, AGENT_KEY)


def test_unfunded_submit_is_409_fund_first(client, auth_headers, hlfake, backend):
    hlfake.unfunded.add(MAIN.address.lower())
    prep = client.post("/api/accounts/approve/prepare", json={"main_address": MAIN.address,
                                                              "agent_address": AGENT.address},
                       headers=auth_headers).json()
    sig = Account.sign_typed_data(MAIN.key, full_message=prep["typed_data"]).signature.hex()
    r = client.post("/api/accounts/approve/submit", headers=auth_headers, json={
        "label": "x", "main_address": MAIN.address, "agent_private_key": AGENT_KEY,
        "action": prep["action"], "nonce": prep["nonce"], "signature": "0x" + sig.removeprefix("0x")})
    assert r.status_code == 409 and "fund it first" in r.json()["detail"]


def test_create_is_rate_limited(client, auth_headers, hlfake, backend):
    codes = [client.post("/api/accounts/create", json={"label": f"a{i}", "passphrase": PASS},
                         headers=auth_headers).status_code for i in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_import_env_migration(client, auth_headers, hlfake, backend, monkeypatch, tmp_path, logs):
    env = tmp_path / "copycat.env"
    env.write_text(f"COPYCAT_ACCOUNT_ADDRESS={MAIN.address}\nCOPYCAT_AGENT_KEY={AGENT_KEY}\n")
    monkeypatch.setenv("COPYCAT_ENV_FILE", str(env))
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS", raising=False)
    st = client.get("/api/accounts/import-env", headers=auth_headers).json()
    assert st == {"available": True, "address": MAIN.address.lower(), "reason": None}
    hlfake.approve(MAIN.address, AGENT.address, name="old")
    r = client.post("/api/accounts/import-env", headers=auth_headers)
    assert r.status_code == 200, r.text
    (acct,) = r.json()
    assert acct["label"] == "Main (from .env)" and acct["active"] is True
    assert client.get("/api/accounts/import-env", headers=auth_headers).json()["available"] is False
    _clean(r.text, AGENT_KEY)
    _clean(logs.text, AGENT_KEY)


def test_import_env_without_env_is_404(client, auth_headers, hlfake, backend, monkeypatch):
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS", raising=False)
    assert client.get("/api/accounts/import-env", headers=auth_headers).json()["available"] is False
    assert client.post("/api/accounts/import-env", headers=auth_headers).status_code == 404
