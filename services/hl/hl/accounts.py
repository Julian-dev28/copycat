"""Account administration on Hyperliquid: agent approval, usdSend, extraAgents.

Used only by services/vault (the owner of every secret). Nothing here stores a
key; callers pass one in for the duration of a single signature and drop it.

Signing reuses the SDK's own user-signed-action code (`sign_agent`,
`sign_usd_transfer_action`, `user_signed_payload`), so the EIP-712 bytes are
exactly what `Exchange.approve_agent` / `Exchange.usd_transfer` would sign. We
do not construct an `Exchange` for these: its constructor makes ~13 network
reads (spotMeta, perpDexs, one meta per dex) that a one-off admin action does
not need. The POST goes through `post_signed_action` with the same body the
SDK's `_post_action` sends.

`post_signed_action` and the reads never raise and never log a payload.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address, to_hex
from hyperliquid.utils import signing

from . import env, rate_limit
from .http import get_session, http_post

logger = logging.getLogger(__name__)

APPROVE_AGENT_PRIMARY = "HyperliquidTransaction:ApproveAgent"
# Same field list the SDK's sign_agent passes (hyperliquid/utils/signing.py).
APPROVE_AGENT_TYPES: List[Dict[str, str]] = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "agentAddress", "type": "address"},
    {"name": "agentName", "type": "string"},
    {"name": "nonce", "type": "uint64"},
]
# Chain the browser wallet signs on. MetaMask refuses eth_signTypedData_v4 when the
# domain chainId differs from the wallet's active chain, so the web switches to it
# first. HL's own frontend uses Arbitrum One on mainnet; testnet uses Arbitrum Sepolia.
SIGNATURE_CHAIN_ID = {"mainnet": "0xa4b1", "testnet": "0x66eee"}


def is_mainnet() -> bool:
    return env.network() == "mainnet"


def hyperliquid_chain() -> str:
    return "Mainnet" if is_mainnet() else "Testnet"


def signature_chain_id() -> str:
    return SIGNATURE_CHAIN_ID[env.network()]


def approve_agent_action(agent_address: str, agent_name: str, nonce: int,
                         chain_id: Optional[str] = None) -> Dict[str, Any]:
    """The approveAgent action exactly as it is posted to /exchange."""
    return {
        "type": "approveAgent",
        "signatureChainId": chain_id or signature_chain_id(),
        "hyperliquidChain": hyperliquid_chain(),
        "agentAddress": _checksum(agent_address),
        "agentName": agent_name,
        "nonce": int(nonce),
    }


def _checksum(addr: str) -> str:
    return to_checksum_address(addr)


def approve_agent_typed_data(action: Dict[str, Any]) -> Dict[str, Any]:
    """EIP-712 typed data for eth_signTypedData_v4, built by the SDK's
    `user_signed_payload`. The message carries only the typed fields: the
    hash is identical (extra keys are not hashed) and strict wallets accept it."""
    message = {f["name"]: action[f["name"]] for f in APPROVE_AGENT_TYPES}
    payload = signing.user_signed_payload(
        APPROVE_AGENT_PRIMARY, APPROVE_AGENT_TYPES,
        {**message, "signatureChainId": action["signatureChainId"]})
    payload["message"] = message
    return payload


def split_signature(sig_hex: str) -> Dict[str, Any]:
    """0x r||s||v (65 bytes) -> {"r", "s", "v"} in the SDK's wire format."""
    raw = bytes.fromhex(sig_hex.removeprefix("0x"))
    if len(raw) != 65:
        raise ValueError("signature must be 65 bytes")
    v = raw[64]
    if v < 27:
        v += 27
    return {"r": to_hex(int.from_bytes(raw[:32], "big")),
            "s": to_hex(int.from_bytes(raw[32:64], "big")), "v": v}


def recover_typed_signer(typed_data: Dict[str, Any], sig: Dict[str, Any]) -> str:
    msg = encode_typed_data(full_message=typed_data)
    return Account.recover_message(msg, vrs=(sig["v"], int(sig["r"], 16), int(sig["s"], 16)))


def sign_approve_agent(main_key: str, agent_address: str, agent_name: str,
                       nonce: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Sign approveAgent with the MAIN key via the SDK's sign_agent.
    Returns (action as posted, signature)."""
    wallet = Account.from_key(main_key)
    action = {"type": "approveAgent", "agentAddress": _checksum(agent_address),
              "agentName": agent_name, "nonce": int(nonce)}
    sig = signing.sign_agent(wallet, action, is_mainnet())   # adds signatureChainId + hyperliquidChain
    return action, sig


def sign_usd_send(main_key: str, destination: str, amount: str,
                  time_ms: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """usdSend (perp USDC to another HL address), signed by the MAIN key via the
    SDK's sign_usd_transfer_action. Returns (action as posted, signature)."""
    wallet = Account.from_key(main_key)
    action = {"destination": destination, "amount": amount, "time": int(time_ms), "type": "usdSend"}
    sig = signing.sign_usd_transfer_action(wallet, action, is_mainnet())
    return action, sig


def post_signed_action(action: Dict[str, Any], nonce: int, signature: Dict[str, Any]) -> Dict[str, Any]:
    """POST a user-signed action to /exchange. Same body as the SDK's _post_action.
    Returns HL's JSON on HTTP 200, else {"status": "err", "response": reason,
    "ambiguous": bool}. Never raises, never logs the body."""
    payload = {"action": action, "nonce": int(nonce), "signature": signature,
               "vaultAddress": None, "expiresAfter": None}
    if not rate_limit.HL_LIMITER.acquire(1, max_wait=2.0):
        logger.warning("[hl.accounts] rate budget wait exceeded, sending %s anyway", action.get("type"))
    try:
        resp = get_session().post(f"{env.base_url()}/exchange", json=payload,
                                  timeout=env.request_timeout_s())
    except Exception as exc:
        logger.error("[hl.accounts] /exchange %s failed: %s", action.get("type"), type(exc).__name__)
        return {"status": "err", "response": f"network error: {type(exc).__name__}", "ambiguous": True}
    code = getattr(resp, "status_code", 0)
    if code != 200:
        text = (getattr(resp, "text", "") or "")[:300]
        logger.error("[hl.accounts] /exchange %s HTTP %s", action.get("type"), code)
        return {"status": "err", "response": f"HTTP {code}: {text}", "ambiguous": code >= 500}
    try:
        body = resp.json()
    except Exception:
        return {"status": "err", "response": "unparseable response", "ambiguous": True}
    return body if isinstance(body, dict) else {"status": "err", "response": str(body)[:300]}


def extra_agents(user: str) -> Optional[List[Dict[str, Any]]]:
    """[{name, address (lowercase), validUntil}] or None on a failed read."""
    raw = http_post("/info", {"type": "extraAgents", "user": user})
    if not isinstance(raw, list):
        return None
    out = []
    for a in raw:
        if isinstance(a, dict) and isinstance(a.get("address"), str):
            vu = a.get("validUntil")
            out.append({"name": str(a.get("name") or ""), "address": a["address"].lower(),
                        "validUntil": int(vu) if isinstance(vu, (int, float)) else None})
    return out


# ── Funding: deposit facts and the three user-signed money actions ─────────────
# Verified 2026-10-05 against Hyperliquid's docs, "USDC > Legacy Bridge"
# (https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/usdc.md):
#   bridge 0x2df1c51e09aecf9cacb7bc98cb1742757f163df7 (mainnet) / 0x08cfc1B6b2dCF36A1480b99353A354AA8AC56f89
#   (testnet); USDC 0xaf88d065e77c8cC2239327C5EDb3A432268e5831 (Arbitrum One, 42161) /
#   0x1baAbB04529D43a73232B713C0FE471f7c7334d5 (Arbitrum Sepolia, 421614); "The minimum deposit
#   amount is 5 USDC. If you send an amount less than this, it will not be credited and be lost
#   forever"; deposits are credited "to the account that sent it in less than 1 minute".
# Exchange endpoint docs, "Initiate a withdrawal request": "There is a $1 fee for withdrawing".
# Cross-checked on chain: each bridge's usdcToken() returns that network's USDC address.
# The docs call this bridge "legacy" and prefer CCTP; it still credits deposits.
FUNDING: Dict[str, Dict[str, Any]] = {
    "mainnet": {"chain_id": 42161, "chain_name": "Arbitrum One",
                "usdc_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                "bridge_address": "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7",
                "explorer_url": "https://arbiscan.io"},
    "testnet": {"chain_id": 421614, "chain_name": "Arbitrum Sepolia",
                "usdc_address": "0x1baAbB04529D43a73232B713C0FE471f7c7334d5",
                "bridge_address": "0x08cfc1B6b2dCF36A1480b99353A354AA8AC56f89",
                "explorer_url": "https://sepolia.arbiscan.io"},
}
MIN_DEPOSIT_USD = 5.0
WITHDRAW_FEE_USD = 1.0
FUNDING_SOURCE = "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/usdc"


def funding_info() -> Dict[str, Any]:
    """Network-specific deposit/withdraw facts (no reads)."""
    net = env.network()
    return {"network": net, **FUNDING[net], "min_deposit_usd": MIN_DEPOSIT_USD,
            "withdraw_fee_usd": WITHDRAW_FEE_USD, "source_url": FUNDING_SOURCE}


# kind -> (action type, EIP-712 primary type, SDK field list, nonce field, SDK signer).
# The field lists ARE the SDK's (hyperliquid/utils/signing.py), so a browser
# signature over our typed data is byte-identical to the SDK's own.
USER_ACTIONS: Dict[str, Tuple[str, str, List[Dict[str, str]], str, Any]] = {
    "usd_class_transfer": ("usdClassTransfer", "HyperliquidTransaction:UsdClassTransfer",
                           signing.USD_CLASS_TRANSFER_SIGN_TYPES, "nonce",
                           signing.sign_usd_class_transfer_action),
    "usd_send": ("usdSend", "HyperliquidTransaction:UsdSend", signing.USD_SEND_SIGN_TYPES, "time",
                 signing.sign_usd_transfer_action),
    "withdraw": ("withdraw3", "HyperliquidTransaction:Withdraw", signing.WITHDRAW_SIGN_TYPES, "time",
                 signing.sign_withdraw_from_bridge_action),
}


def user_action_keys(kind: str) -> set:
    """The exact key set of a posted action of this kind."""
    _, _, types, nonce_field, _ = USER_ACTIONS[kind]
    return {"type", "signatureChainId"} | {f["name"] for f in types} | {nonce_field}


def _bare_action(kind: str, amount: str, nonce: int, to_perp: Optional[bool],
                 destination: Optional[str]) -> Dict[str, Any]:
    atype, _, _, nonce_field, _ = USER_ACTIONS[kind]
    action: Dict[str, Any] = {"type": atype, "amount": amount, nonce_field: int(nonce)}
    if kind == "usd_class_transfer":
        action["toPerp"] = bool(to_perp)
    else:
        action["destination"] = destination
    return action


def user_action(kind: str, amount: str, nonce: int, to_perp: Optional[bool] = None,
                destination: Optional[str] = None, chain_id: Optional[str] = None) -> Dict[str, Any]:
    """The action exactly as posted to /exchange, for a browser wallet to sign."""
    return {**_bare_action(kind, amount, nonce, to_perp, destination),
            "signatureChainId": chain_id or signature_chain_id(), "hyperliquidChain": hyperliquid_chain()}


def user_action_typed_data(kind: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """EIP-712 typed data via the SDK's user_signed_payload, message = typed fields only."""
    _, primary, types, _, _ = USER_ACTIONS[kind]
    message = {f["name"]: action[f["name"]] for f in types}
    payload = signing.user_signed_payload(primary, types, {**message, "signatureChainId": action["signatureChainId"]})
    payload["message"] = message
    return payload


def sign_user_action(main_key: str, kind: str, amount: str, nonce: int, to_perp: Optional[bool] = None,
                     destination: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Sign with the MAIN key through the SDK's own sign_* function (it adds
    signatureChainId 0x66eee + hyperliquidChain). Returns (action as posted, signature)."""
    wallet = Account.from_key(main_key)
    action = _bare_action(kind, amount, nonce, to_perp, destination)
    sig = USER_ACTIONS[kind][4](wallet, action, is_mainnet())
    return action, sig


def action_type(kind: str) -> str:
    return USER_ACTIONS[kind][0]
