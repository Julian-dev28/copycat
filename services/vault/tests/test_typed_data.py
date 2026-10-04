"""prepare_agent_approval builds the exact EIP-712 data the SDK signs."""
from __future__ import annotations

from eth_account import Account
from hl import accounts as acc
from hyperliquid.utils import signing
from vault import public

MAIN = Account.from_key("0x" + "11" * 32)
AGENT = Account.from_key("0x" + "22" * 32)


def _sig_hex(sig) -> str:
    return "0x" + int(sig["r"], 16).to_bytes(32, "big").hex() + int(sig["s"], 16).to_bytes(32, "big").hex() \
        + bytes([sig["v"]]).hex()


def test_typed_data_matches_the_sdk_signer_byte_for_byte():
    out = public.prepare_agent_approval(MAIN.address, AGENT.address, "copycat")
    td, action, nonce = out["typed_data"], out["action"], out["nonce"]
    assert td["domain"]["name"] == "HyperliquidSignTransaction"
    assert td["domain"]["chainId"] == int(action["signatureChainId"], 16) == 0xa4b1   # mainnet
    assert td["primaryType"] == "HyperliquidTransaction:ApproveAgent"
    assert set(td["message"]) == {"hyperliquidChain", "agentAddress", "agentName", "nonce"}
    assert action["nonce"] == nonce and action["hyperliquidChain"] == "Mainnet"

    # What a browser wallet does: sign the typed data as-is.
    browser = Account.sign_typed_data(MAIN.key, full_message=td)
    # What the SDK does for the same action (sign_user_signed_action keeps our chain id
    # only if we pin it; it hard-codes 0x66eee, so compare at 0x66eee too).
    sdk_action = {"type": "approveAgent", "agentAddress": AGENT.address, "agentName": "copycat",
                  "nonce": nonce}
    sdk_sig = signing.sign_agent(MAIN, sdk_action, True)
    ours_66eee = acc.approve_agent_typed_data(acc.approve_agent_action(AGENT.address, "copycat", nonce, "0x66eee"))
    again = Account.sign_typed_data(MAIN.key, full_message=ours_66eee)
    assert (int(sdk_sig["r"], 16), int(sdk_sig["s"], 16), sdk_sig["v"]) == (again.r, again.s, again.v)
    # recovery through our helper
    assert acc.recover_typed_signer(td, acc.split_signature(browser.signature.hex())).lower() == \
        MAIN.address.lower()
    assert acc.recover_typed_signer(ours_66eee, sdk_sig) == MAIN.address


def test_testnet_uses_arbitrum_sepolia_and_testnet_chain(monkeypatch):
    monkeypatch.setenv("COPYCAT_NETWORK", "testnet")
    out = public.prepare_agent_approval(MAIN.address, AGENT.address, "copycat")
    assert out["action"]["signatureChainId"] == "0x66eee"
    assert out["typed_data"]["message"]["hyperliquidChain"] == "Testnet"


def test_split_signature_normalizes_v_and_matches_sdk_wire_format():
    signed = Account.sign_typed_data(MAIN.key, full_message=public.prepare_agent_approval(
        MAIN.address, AGENT.address, "x")["typed_data"])
    raw = bytes(signed.signature)
    low_v = "0x" + (raw[:64] + bytes([raw[64] - 27])).hex()
    a, b = acc.split_signature("0x" + raw.hex()), acc.split_signature(low_v)
    assert a == b and a["v"] in (27, 28) and a["r"].startswith("0x")
    assert _sig_hex(a) == "0x" + raw.hex()
