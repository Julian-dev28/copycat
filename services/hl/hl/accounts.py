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
