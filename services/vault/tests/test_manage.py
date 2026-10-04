"""activate / rename / remove / refresh / transfer / statuses / credentials."""
from __future__ import annotations

import time

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.utils import signing
from vault import agents, public, store
from vault.errors import InvalidRequest, NeedsBrowserSignIn, WrongPassphrase

from contracts.models import AgentStatus

PASS = "correct horse battery staple"
NOW = int(time.time() * 1000)
DAY = 24 * 3600 * 1000


def _connected(fake_hl, n: int, label: str = "c"):
    main = Account.from_key("0x" + f"{n:02x}" * 32)
    key = "0x" + f"{n + 1:02x}" * 32
    fake_hl.approve(main.address, Account.from_key(key).address)
    return public.import_api_key(label, main.address, key), key


def test_activation_makes_the_vault_authoritative_and_switches_credentials(fake_hl):
    a, key_a = _connected(fake_hl, 0x10, "A")
    b, key_b = _connected(fake_hl, 0x20, "B")
    assert public.is_authoritative() is False and public.active_credentials() is None
    public.set_active(a.id)
    assert public.is_authoritative() and public.active_credentials() == (a.address, key_a)
    public.set_active(b.id)
    assert public.active_credentials() == (b.address, key_b)
    assert [x.active for x in public.list_accounts(refresh_status=False)] == [False, True]


def test_removing_the_active_account_stops_trading_and_never_falls_back(fake_hl):
    a, _ = _connected(fake_hl, 0x10)
    public.set_active(a.id)
    public.remove(a.id)
    assert public.is_authoritative() and public.active_address() is None
    assert public.active_credentials() is None


def test_remove_archives_a_created_main_key_instead_of_deleting_it(fake_hl, vault_env):
    acct, _, _ = public.create_account("C", PASS)
    public.remove(acct.id)
    assert (vault_env / "vault" / "removed" / f"{acct.id}.main.json").exists()
    assert not (vault_env / "vault" / "keys" / f"{acct.id}.agent.json").exists()


def test_rename_validates_and_unknown_ids_are_404(fake_hl):
    a, _ = _connected(fake_hl, 0x10)
    assert public.rename(a.id, "New name").label == "New name"
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        public.rename(a.id, "")
    from vault.errors import AccountNotFound
    for bad in ("acc_0000000000000000", "../../etc/passwd", ""):
        with pytest.raises(AccountNotFound):
            public.set_active(bad)


def test_refresh_connected_accounts_must_rerun_sign_in(fake_hl):
    a, _ = _connected(fake_hl, 0x10)
    with pytest.raises(NeedsBrowserSignIn, match="re-run sign-in"):
        public.refresh_agent(a.id, PASS)


def test_refresh_created_needs_the_right_passphrase(fake_hl):
    acct, _, _ = public.create_account("C", PASS)
    for bad in (None, "", "wrong passphrase!!"):
        with pytest.raises(WrongPassphrase):
            public.refresh_agent(acct.id, bad)


def test_transfer_requires_passphrase_created_source_and_a_vault_destination(fake_hl):
    src, _, _ = public.create_account("Src", PASS)
    dst, _ = _connected(fake_hl, 0x10)
    with pytest.raises(WrongPassphrase):
        public.transfer(src.id, dst.address, 5.0, "wrong passphrase!!")
    with pytest.raises(InvalidRequest, match="another account"):
        public.transfer(src.id, "0x" + "99" * 20, 5.0, PASS)
    with pytest.raises(InvalidRequest, match="created"):
        public.transfer(dst.id, src.address, 5.0, PASS)
    n = len(fake_hl.posts)
    out = public.transfer(src.id, dst.address, 12.3456789, PASS)
    assert out == {"ok": True, "from_address": src.address, "to_address": dst.address, "amount_usd": 12.345678}
    post = fake_hl.posts[n]
    assert post["action"]["type"] == "usdSend" and post["action"]["amount"] == "12.345678"
    assert post["action"]["destination"] == dst.address and post["action"]["hyperliquidChain"] == "Mainnet"
    payload = signing.user_signed_payload("HyperliquidTransaction:UsdSend", signing.USD_SEND_SIGN_TYPES,
                                          post["action"])
    sig = post["signature"]
    recovered = Account.recover_message(encode_typed_data(full_message=payload),
                                        vrs=(sig["v"], int(sig["r"], 16), int(sig["s"], 16)))
    assert recovered.lower() == src.address


@pytest.mark.parametrize("rows,stored,expect", [
    (None, NOW + 5 * DAY, AgentStatus.unknown),
    ([], None, AgentStatus.missing),
    ([], NOW - DAY, AgentStatus.expired),
    ([{"address": "0xa", "validUntil": NOW - 1}], None, AgentStatus.expired),
    ([{"address": "0xa", "validUntil": NOW + 29 * DAY}], None, AgentStatus.expiring),
    ([{"address": "0xa", "validUntil": NOW + 30 * DAY}], None, AgentStatus.expiring),
    ([{"address": "0xa", "validUntil": NOW + 31 * DAY}], None, AgentStatus.active),
])
def test_agent_status_classification(rows, stored, expect):
    assert agents.classify("0xA", rows, stored, NOW)[0] == expect
    assert agents.classify(None, rows, stored, NOW)[0] == AgentStatus.missing


def test_extra_agents_cache_10_min_and_failures_30_s(fake_hl, monkeypatch):
    calls = []
    real = fake_hl.extra_agents
    from vault import hlops
    monkeypatch.setattr(hlops, "extra_agents", lambda u: calls.append(u) or real(u))
    t = [1000.0]
    monkeypatch.setattr(agents, "_clock", lambda: t[0])
    agents.lookup("0xabc")
    t[0] += 599
    agents.lookup("0xabc")
    assert len(calls) == 1
    t[0] += 2
    agents.lookup("0xabc")
    assert len(calls) == 2
    fake_hl.read_fails = True
    agents.lookup("0xabc", force=True)
    t[0] += 31
    agents.lookup("0xabc")
    assert len(calls) == 4


def test_list_accounts_persists_status_changes(fake_hl):
    a, _ = _connected(fake_hl, 0x10)
    fake_hl.agents.clear()
    agents.invalidate()
    assert public.list_accounts()[0].agent_status == AgentStatus.missing
    assert store.load()["accounts"][0]["agent_status"] == "missing"
