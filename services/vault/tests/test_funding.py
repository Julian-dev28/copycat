"""Funding: usdClassTransfer / usdSend / withdraw3 on both signing paths.

Typed data must equal the SDK's construction byte for byte (a browser signature
over ours == the SDK's signature over the same action), the signer must be the
account's own address, and every guard must hold on prepare, submit and the
passphrase path. Hyperliquid is the conftest FakeHL: nothing leaves the machine.
"""
from __future__ import annotations

import json
import time

import pytest
from eth_account import Account
from hl import accounts as acc
from hyperliquid.utils import signing
from vault import audit, funding, public
from vault.errors import HlRejected, HlUnavailable, InvalidRequest, SignatureMismatch, WrongPassphrase

PASS = "correct horse battery staple"
MAIN = Account.from_key("0x" + "31" * 32)
OTHER = Account.from_key("0x" + "41" * 32)
OUTSIDE = "0x" + "99" * 20

SDK = {
    "usd_class_transfer": ({"type": "usdClassTransfer", "amount": "2.5", "toPerp": True, "nonce": 1_700_000_000_000},
                           signing.sign_usd_class_transfer_action),
    "usd_send": ({"type": "usdSend", "destination": OUTSIDE, "amount": "2.5", "time": 1_700_000_000_000},
                 signing.sign_usd_transfer_action),
    "withdraw": ({"type": "withdraw3", "destination": OUTSIDE, "amount": "2.5", "time": 1_700_000_000_000},
                 signing.sign_withdraw_from_bridge_action),
}


def _connected(fake_hl, main=MAIN, n=0x32):
    key = "0x" + f"{n:02x}" * 32
    fake_hl.approve(main.address, Account.from_key(key).address)
    return public.import_api_key("conn", main.address, key)


def _sign(td, who=MAIN) -> str:
    return "0x" + bytes(Account.sign_typed_data(who.key, full_message=td).signature).hex()


@pytest.mark.parametrize("kind", list(SDK))
def test_typed_data_equals_the_sdk_construction(kind):
    sdk_action, sdk_sign = SDK[kind]
    bare = dict(sdk_action)
    sdk_sig = sdk_sign(MAIN, bare, True)               # SDK pins signatureChainId 0x66eee
    ours = acc.user_action(kind, "2.5", 1_700_000_000_000, to_perp=sdk_action.get("toPerp"),
                           destination=sdk_action.get("destination"), chain_id="0x66eee")
    assert ours == bare                                # same action dict the SDK posts
    td = acc.user_action_typed_data(kind, ours)
    browser = Account.sign_typed_data(MAIN.key, full_message=td)
    assert (int(sdk_sig["r"], 16), int(sdk_sig["s"], 16), sdk_sig["v"]) == (browser.r, browser.s, browser.v)
    assert acc.recover_typed_signer(td, sdk_sig) == MAIN.address
    assert set(ours) == acc.user_action_keys(kind)


def test_prepare_uses_arbitrum_one_on_mainnet_and_sepolia_on_testnet(fake_hl, monkeypatch):
    a = _connected(fake_hl)
    out = public.prepare_user_action(a.id, "withdraw", 3, 10)
    assert out["typed_data"]["domain"]["chainId"] == 0xa4b1
    assert out["typed_data"]["primaryType"] == "HyperliquidTransaction:Withdraw"
    assert out["action"]["destination"] == a.address and out["action"]["time"] == out["nonce"]
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    out = public.prepare_user_action(a.id, "usd_class_transfer", 1, 10, to_perp=True)
    assert out["action"]["signatureChainId"] == "0x66eee" and out["action"]["hyperliquidChain"] == "Testnet"
    assert out["typed_data"]["message"] == {"hyperliquidChain": "Testnet", "amount": "1", "toPerp": True,
                                            "nonce": out["nonce"]}


@pytest.mark.parametrize("kind,kw", [("usd_class_transfer", {"to_perp": True}), ("usd_class_transfer", {"to_perp": False}),
                                     ("withdraw", {}), ("usd_send", {"dest": True})])
def test_browser_path_posts_exactly_what_the_wallet_signed(fake_hl, kind, kw):
    a = _connected(fake_hl)
    b = _connected(fake_hl, OTHER, 0x42)
    dest = b.address if kw.get("dest") else None
    prep = public.prepare_user_action(a.id, kind, 4.25, 10, to_perp=kw.get("to_perp"), destination=dest)
    sig = _sign(prep["typed_data"])
    n = len(fake_hl.posts)
    out = public.submit_user_action(a.id, kind, prep["action"], prep["nonce"], sig, 10)
    assert out["ok"] and out["amount_usd"] == 4.25 and out["account_address"] == a.address
    post = fake_hl.posts[n]
    assert post["action"] == prep["action"] and post["nonce"] == prep["nonce"]
    assert acc.recover_typed_signer(acc.user_action_typed_data(kind, post["action"]), post["signature"]).lower() \
        == a.address
    if kind == "withdraw":
        assert out["destination"] == a.address and out["fee_usd"] == 1.0


def test_signer_mismatch_is_rejected_and_nothing_is_posted(fake_hl):
    a = _connected(fake_hl)
    prep = public.prepare_user_action(a.id, "withdraw", 3, 10)
    n = len(fake_hl.posts)
    with pytest.raises(SignatureMismatch):
        public.submit_user_action(a.id, "withdraw", prep["action"], prep["nonce"], _sign(prep["typed_data"], OTHER), 10)
    # a tampered amount (still under the cap) no longer matches the signature
    tampered = {**prep["action"], "amount": "2"}
    with pytest.raises(SignatureMismatch):
        public.submit_user_action(a.id, "withdraw", tampered, prep["nonce"], _sign(prep["typed_data"]), 10)
    with pytest.raises(InvalidRequest, match="signature"):
        public.submit_user_action(a.id, "withdraw", prep["action"], prep["nonce"], "0xdead", 10)
    assert len(fake_hl.posts) == n
    assert [r["outcome"] for r in audit.read()][-3:] == ["refused"] * 3


def test_submit_rechecks_shape_chain_and_age(fake_hl):
    a = _connected(fake_hl)
    prep = public.prepare_user_action(a.id, "withdraw", 3, 10)
    sig = _sign(prep["typed_data"])
    bad = [({**prep["action"], "extra": 1}, "exactly the keys"),
           ({**prep["action"], "type": "usdSend"}, "withdraw3"),
           ({**prep["action"], "hyperliquidChain": "Testnet"}, "Mainnet"),
           ({**prep["action"], "amount": "3e0"}, "plain decimal"),
           ({**prep["action"], "time": prep["nonce"] + 1}, "must equal nonce")]
    for action, msg in bad:
        with pytest.raises(InvalidRequest, match=msg):
            public.submit_user_action(a.id, "withdraw", action, prep["nonce"], sig, 10)
    old = int(time.time() * 1000) - 11 * 60 * 1000
    stale = {**prep["action"], "time": old}
    with pytest.raises(InvalidRequest, match="expired"):
        public.submit_user_action(a.id, "withdraw", stale, old, sig, 10)
    # an action for another kind does not validate as this kind
    with pytest.raises(InvalidRequest, match="exactly the keys"):
        public.submit_user_action(a.id, "usd_class_transfer", prep["action"], prep["nonce"], sig, 10)


def test_withdraw_destination_defaults_to_own_and_any_other_needs_a_typed_confirm(fake_hl):
    a = _connected(fake_hl)
    assert public.prepare_user_action(a.id, "withdraw", 3, 10)["action"]["destination"] == a.address
    with pytest.raises(InvalidRequest, match="confirm_destination"):
        public.prepare_user_action(a.id, "withdraw", 3, 10, destination=OUTSIDE)
    with pytest.raises(InvalidRequest, match="confirm_destination"):
        public.prepare_user_action(a.id, "withdraw", 3, 10, destination=OUTSIDE, confirm_destination="0x" + "98" * 20)
    prep = public.prepare_user_action(a.id, "withdraw", 3, 10, destination=OUTSIDE,
                                      confirm_destination=OUTSIDE.upper().replace("0X", "0x"))
    assert prep["action"]["destination"] == OUTSIDE
    sig = _sign(prep["typed_data"])
    with pytest.raises(InvalidRequest, match="confirm_destination"):     # submit re-checks
        public.submit_user_action(a.id, "withdraw", prep["action"], prep["nonce"], sig, 10)
    out = public.submit_user_action(a.id, "withdraw", prep["action"], prep["nonce"], sig, 10,
                                    confirm_destination=OUTSIDE)
    assert out["destination"] == OUTSIDE
    with pytest.raises(InvalidRequest, match="fee"):
        public.prepare_user_action(a.id, "withdraw", 1, 10)


@pytest.mark.parametrize("amount,cap,err", [(0, 10, InvalidRequest), (-1, 10, InvalidRequest),
                                            (10.01, 10, InvalidRequest), (5, None, HlUnavailable),
                                            ("abc", 10, InvalidRequest), (0.0000001, 10, InvalidRequest)])
def test_amount_bounds(fake_hl, amount, cap, err):
    a = _connected(fake_hl)
    with pytest.raises(err):
        public.prepare_user_action(a.id, "usd_class_transfer", amount, cap, to_perp=True)


def test_amount_at_the_cap_passes_and_rounds_down():
    assert funding.amount_str(0.1100009) == "0.11"
    assert funding.amount_str(12.3456789) == "12.345678"
    assert funding.amount_str("5") == "5"


def test_send_goes_only_to_another_vault_account_and_class_transfer_rules(fake_hl):
    a = _connected(fake_hl)
    with pytest.raises(InvalidRequest, match="another account"):
        public.prepare_user_action(a.id, "usd_send", 2, 10, destination=OUTSIDE)
    with pytest.raises(InvalidRequest, match="this account"):
        public.prepare_user_action(a.id, "usd_send", 2, 10, destination=a.address)
    with pytest.raises(InvalidRequest, match="to_perp is required"):
        public.prepare_user_action(a.id, "usd_class_transfer", 2, 10)
    with pytest.raises(InvalidRequest, match="no destination"):
        public.prepare_user_action(a.id, "usd_class_transfer", 2, 10, to_perp=True, destination=OUTSIDE)
    with pytest.raises(InvalidRequest, match="unified"):
        public.prepare_user_action(a.id, "usd_class_transfer", 2, 10, to_perp=True, unified=True)
    with pytest.raises(InvalidRequest, match="to_perp only"):
        public.prepare_user_action(a.id, "withdraw", 2, 10, to_perp=True)
    with pytest.raises(InvalidRequest, match="kind"):
        public.prepare_user_action(a.id, "bridge_everything", 2, 10)


def test_passphrase_path_signs_with_the_main_key_via_the_sdk(fake_hl):
    src, key, _ = public.create_account("Src", PASS)
    conn = _connected(fake_hl)
    with pytest.raises(WrongPassphrase):
        public.run_user_action(src.id, "withdraw", 3, 10, "wrong passphrase!!")
    with pytest.raises(InvalidRequest, match="browser wallet"):
        public.run_user_action(conn.id, "withdraw", 3, 10, PASS)
    for kind, kw in (("usd_class_transfer", {"to_perp": True}), ("withdraw", {}),
                     ("usd_send", {"destination": conn.address})):
        n = len(fake_hl.posts)
        out = public.run_user_action(src.id, kind, 3, 10, PASS, **kw)
        post = fake_hl.posts[n]
        assert out["ok"] and post["action"]["amount"] == "3" and post["action"]["signatureChainId"] == "0x66eee"
        assert acc.recover_typed_signer(acc.user_action_typed_data(kind, post["action"]),
                                        post["signature"]).lower() == src.address
    assert fake_hl.posts[-2]["action"]["destination"] == src.address        # withdraw: own by default


def test_hl_rejection_is_audited_and_raised(fake_hl):
    src, _, _ = public.create_account("Src", PASS)
    fake_hl.reject = "Insufficient balance for withdrawal"
    with pytest.raises(HlRejected, match="Insufficient"):
        public.run_user_action(src.id, "withdraw", 3, 10, PASS)
    last = audit.read()[-1]
    assert last["outcome"] == "rejected" and last["action"] == "withdraw" and last["path"] == "passphrase"


def test_audit_log_has_every_attempt_and_no_secret(fake_hl, vault_env):
    src, main_key, _ = public.create_account("Src", PASS)
    a = _connected(fake_hl)
    public.run_user_action(src.id, "withdraw", 3, 10, PASS)
    with pytest.raises(WrongPassphrase):
        public.run_user_action(src.id, "withdraw", 3, 10, "a wrong passphrase")
    prep = public.prepare_user_action(a.id, "usd_class_transfer", 2, 10, to_perp=False)
    sig = _sign(prep["typed_data"])
    public.submit_user_action(a.id, "usd_class_transfer", prep["action"], prep["nonce"], sig, 10)
    rows = audit.read()
    assert [(r["action"], r["path"], r["outcome"]) for r in rows] == [
        ("withdraw", "passphrase", "ok"), ("withdraw", "passphrase", "refused"),
        ("usd_class_transfer", "browser", "ok")]
    assert rows[0]["destination"] == src.address and rows[2]["to_perp"] is False and rows[2]["amount_usd"] == 2.0
    path = vault_env / "vault" / "audit.jsonl"
    assert (path.stat().st_mode & 0o777) == 0o600
    text = path.read_text()
    secrets = [PASS, "a wrong passphrase", main_key.removeprefix("0x"), sig.removeprefix("0x")[:64],
               sig.removeprefix("0x")[64:128]]
    for s in secrets:
        assert s not in text
    for line in text.splitlines():
        assert set(json.loads(line)) == {"ts_ms", "action", "path", "outcome", "account_id", "address",
                                         "amount_usd", "to_perp", "destination", "nonce", "reason"}
    with pytest.raises(ValueError):
        audit.record(kind="withdraw", signature="0x00")
