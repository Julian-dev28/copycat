"""hl.env resolves credentials vault-first once the vault is authoritative, and
hl.sdk.get_exchange rebuilds when the active account changes."""
from __future__ import annotations

import pytest
from eth_account import Account
from hl import env, sdk
from vault import public

ENV_MAIN = "0x" + "77" * 20
ENV_KEY = "0x" + "78" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", ENV_MAIN)
    monkeypatch.setenv("COPYCAT_AGENT_KEY", ENV_KEY)
    sdk.reset()
    yield
    sdk.reset()


def _connected(fake_hl, n):
    main = Account.from_key("0x" + f"{n:02x}" * 32)
    key = "0x" + f"{n + 1:02x}" * 32
    fake_hl.approve(main.address, Account.from_key(key).address)
    return public.import_api_key(f"acct{n}", main.address, key), key


def test_env_vars_trade_until_the_first_activation(fake_hl):
    assert env.credentials() == (ENV_MAIN, ENV_KEY)
    a, key = _connected(fake_hl, 0x10)
    assert env.credentials() == (ENV_MAIN, ENV_KEY)        # creating an account changes nothing
    public.set_active(a.id)
    assert env.credentials() == (a.address, key)
    assert env.account_address() == a.address and env.has_write_creds()
    public.remove(a.id)
    assert env.credentials() == ("", "") and not env.has_write_creds()   # never back to .env


def test_unreadable_vault_fails_closed(fake_hl, vault_env):
    a, _ = _connected(fake_hl, 0x10)
    public.set_active(a.id)
    (vault_env / "vault" / "accounts.json").write_text("{not json")
    assert env.credentials() == ("", "") and env.account_address() == ""


def test_get_exchange_rebuilds_when_the_active_account_changes(fake_hl, monkeypatch):
    built = []

    class _FakeEx:
        def __init__(self, wallet, account_address, **kw):
            built.append((wallet.address.lower(), account_address))

    monkeypatch.setattr(sdk, "Exchange", _FakeEx)
    monkeypatch.setattr(sdk, "_perp_dexs_arg", lambda: None)
    a, ka = _connected(fake_hl, 0x10)
    b, kb = _connected(fake_hl, 0x20)
    public.set_active(a.id)
    ex1 = sdk.get_exchange()
    assert sdk.get_exchange() is ex1
    public.set_active(b.id)
    ex2 = sdk.get_exchange()
    assert ex2 is not ex1
    assert built == [(Account.from_key(ka).address.lower(), a.address),
                     (Account.from_key(kb).address.lower(), b.address)]


def test_main_key_guard_still_applies_to_env_creds(monkeypatch):
    key = "0x" + "33" * 32
    monkeypatch.setenv("COPYCAT_AGENT_KEY", key)
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", Account.from_key(key).address)
    monkeypatch.setattr(sdk, "Exchange", lambda **kw: pytest.fail("must not build"))
    with pytest.raises(sdk.MainWalletKeyError):
        sdk.get_exchange()
