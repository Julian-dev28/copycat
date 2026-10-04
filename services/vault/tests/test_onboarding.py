"""create / import key / browser sign-in, against a fake HL."""
from __future__ import annotations

import time

import pytest
from eth_account import Account
from vault import public, store
from vault.errors import HlUnavailable, InvalidRequest, MainKeyRefused, SignatureMismatch

from contracts.models import AccountKind, AgentStatus

PASS = "correct horse battery staple"
MAIN = Account.from_key("0x" + "11" * 32)
AGENT_KEY = "0x" + "22" * 32
AGENT = Account.from_key(AGENT_KEY)


def _signed(main=MAIN, agent=AGENT, name="copycat"):
    out = public.prepare_agent_approval(main.address, agent.address, name)
    sig = Account.sign_typed_data(main.key, full_message=out["typed_data"]).signature.hex()
    return out, "0x" + sig.removeprefix("0x")


# ── create ──────────────────────────────────────────────────────────────────

def test_create_account_stores_main_key_encrypted_and_returns_it_once(fake_hl, vault_env, monkeypatch):
    real_post = fake_hl.post_signed_action

    def unfunded(action, nonce, sig):
        fake_hl.unfunded.add(fake_hl._signer(action, sig))
        return real_post(action, nonce, sig)
    from vault import hlops
    monkeypatch.setattr(hlops, "post_signed_action", unfunded)
    acct, key, warning = public.create_account("Fresh", PASS)
    assert acct.kind == AccountKind.created and acct.has_main_key
    assert Account.from_key(key).address.lower() == acct.address
    assert acct.agent_status == AgentStatus.missing and acct.agent_address is None
    assert "fund it first" in warning and "Refresh agent" in warning and acct.address in warning
    for p in (vault_env / "vault").rglob("*"):
        if p.is_file():
            assert key.removeprefix("0x") not in p.read_text(errors="ignore")
    assert public.list_accounts(refresh_status=False)[0].id == acct.id

    # funded later: refresh signs a new approval with the unlocked main key
    monkeypatch.setattr(hlops, "post_signed_action", real_post)
    fake_hl.unfunded.clear()
    fresh = public.refresh_agent(acct.id, PASS)
    assert fresh.agent_status == AgentStatus.active and fresh.agent_address
    assert fake_hl.posts[-1]["action"]["agentName"] == "copycat"


def test_create_funded_path_approves_immediately(fake_hl):
    acct, _, warning = public.create_account("Main", PASS)
    assert acct.agent_status == AgentStatus.active and acct.agent_valid_until_ms
    assert "not approved" not in warning
    assert store.read_agent_key(acct.id)


# ── import an API wallet key ────────────────────────────────────────────────

def test_import_refuses_the_main_key_itself(fake_hl):
    with pytest.raises(MainKeyRefused) as e:
        public.import_api_key("x", MAIN.address, "0x" + "11" * 32)
    assert "11" * 32 not in str(e.value)
    assert not store.exists() or public.list_accounts(refresh_status=False) == []


def test_import_requires_hl_to_list_the_agent(fake_hl):
    with pytest.raises(InvalidRequest, match="not an approved API wallet"):
        public.import_api_key("x", MAIN.address, AGENT_KEY)
    fake_hl.read_fails = True
    with pytest.raises(HlUnavailable):
        public.import_api_key("x", MAIN.address, AGENT_KEY)


def test_import_takes_valid_until_from_extra_agents(fake_hl):
    vu = int(time.time() * 1000) + 10 * 24 * 3600 * 1000
    fake_hl.approve(MAIN.address, AGENT.address, name="hypememe", valid_until=vu)
    acct = public.import_api_key("Bot", MAIN.address.upper().replace("0X", "0x"), AGENT_KEY)
    assert acct.kind == AccountKind.connected_key and acct.agent_name == "hypememe"
    assert acct.agent_valid_until_ms == vu and acct.agent_status == AgentStatus.expiring
    assert store.read_agent_key(acct.id) == AGENT_KEY


def test_import_rejects_an_expired_agent_and_garbage_keys(fake_hl):
    fake_hl.approve(MAIN.address, AGENT.address, valid_until=int(time.time() * 1000) - 1)
    with pytest.raises(InvalidRequest, match="expired"):
        public.import_api_key("x", MAIN.address, AGENT_KEY)
    with pytest.raises(InvalidRequest, match="not a valid private key") as e:
        public.import_api_key("x", MAIN.address, "0xnot-a-key-zz")
    assert "not-a-key" not in str(e.value)


# ── sign in with a browser wallet ───────────────────────────────────────────

def test_submit_verifies_signer_posts_confirms_and_stores(fake_hl):
    fake_hl.listing_delay = 2              # HL lists the agent on the 3rd read
    out, sig = _signed()
    acct = public.submit_agent_approval("Ledger", MAIN.address, AGENT_KEY, out["action"], out["nonce"], sig)
    assert acct.kind == AccountKind.connected_signed and acct.agent_status == AgentStatus.active
    post = fake_hl.posts[-1]
    assert post["action"]["agentAddress"].lower() == AGENT.address.lower()
    assert post["nonce"] == out["nonce"] and set(post["signature"]) == {"r", "s", "v"}


def test_submit_rejects_a_signature_from_the_wrong_signer(fake_hl):
    other = Account.from_key("0x" + "33" * 32)
    out = public.prepare_agent_approval(MAIN.address, AGENT.address, "copycat")
    sig = Account.sign_typed_data(other.key, full_message=out["typed_data"]).signature.hex()
    with pytest.raises(SignatureMismatch):
        public.submit_agent_approval("x", MAIN.address, AGENT_KEY, out["action"], out["nonce"], "0x" + sig)
    assert fake_hl.posts == []


def test_submit_rejects_tampered_action_and_mismatched_agent_key(fake_hl):
    out, sig = _signed()
    with pytest.raises(InvalidRequest, match="does not belong"):
        public.submit_agent_approval("x", MAIN.address, "0x" + "44" * 32, out["action"], out["nonce"], sig)
    bad = {**out["action"], "agentName": "evil"}
    with pytest.raises(SignatureMismatch):
        public.submit_agent_approval("x", MAIN.address, AGENT_KEY, bad, out["nonce"], sig)
    with pytest.raises(InvalidRequest, match="exactly the keys"):
        public.submit_agent_approval("x", MAIN.address, AGENT_KEY, {**out["action"], "x": 1}, out["nonce"], sig)
    with pytest.raises(MainKeyRefused):
        public.submit_agent_approval("x", MAIN.address, "0x" + "11" * 32, out["action"], out["nonce"], sig)
    assert fake_hl.posts == []


def test_submit_refuses_a_stale_nonce(fake_hl, monkeypatch):
    out, sig = _signed()
    from vault import approval
    monkeypatch.setattr(approval, "now_ms", lambda: out["nonce"] + 16 * 60 * 1000)
    from vault import onboarding
    monkeypatch.setattr(onboarding, "now_ms", lambda: out["nonce"] + 16 * 60 * 1000)
    with pytest.raises(InvalidRequest, match="expired"):
        public.submit_agent_approval("x", MAIN.address, AGENT_KEY, out["action"], out["nonce"], sig)


def test_resubmitting_replaces_the_previous_agent_on_the_same_account(fake_hl):
    out, sig = _signed()
    first = public.submit_agent_approval("A", MAIN.address, AGENT_KEY, out["action"], out["nonce"], sig)
    new_key = "0x" + "55" * 32
    out2, sig2 = _signed(agent=Account.from_key(new_key))
    second = public.submit_agent_approval("A2", MAIN.address, new_key, out2["action"], out2["nonce"], sig2)
    assert second.id == first.id and second.label == "A2"
    assert store.read_agent_key(first.id) == new_key
    assert len(public.list_accounts(refresh_status=False)) == 1


def test_submit_unfunded_main_says_fund_first(fake_hl):
    fake_hl.unfunded.add(MAIN.address.lower())
    out, sig = _signed()
    from vault.errors import NeedsFunding
    with pytest.raises(NeedsFunding, match="fund it first"):
        public.submit_agent_approval("x", MAIN.address, AGENT_KEY, out["action"], out["nonce"], sig)
