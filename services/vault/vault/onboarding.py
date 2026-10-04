"""The three ways an account enters the vault: create, connect by browser
signature (prepare + submit), connect by pasted API wallet key."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from eth_account import Account

from contracts.models import AccountKind, AgentStatus, TradingAccount

from . import agents, fsio, hlops, store
from .approval import (
    approve_with_main_key,
    key_to_address,
    norm_address,
    now_ms,
    require_ok,
    save_agent,
)
from .approval import confirm as confirm_agent
from .errors import (
    HlUnavailable,
    InvalidRequest,
    MainKeyRefused,
    SignatureMismatch,
    VaultError,
)

BACKUP_WARNING = ("This is the private key of your new wallet. It is shown once and never again. "
                  "Write it down offline: it is the only way to recover the funds if this machine "
                  "or your passphrase is lost.")
MAIN_KEY_REFUSED = ("That is the private key of {main} itself (your main wallet). It can withdraw your "
                    "funds, so copycat never stores it. Create an API wallet at "
                    "https://app.hyperliquid.xyz/API and paste ITS key.")
NONCE_MAX_AGE_MS = 15 * 60 * 1000
_NAME_RE = re.compile(r"^[A-Za-z0-9 _\-]{0,16}$")
_CHAIN_RE = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
_ACTION_KEYS = {"type", "signatureChainId", "hyperliquidChain", "agentAddress", "agentName", "nonce"}


def create_account(label: str, passphrase: str) -> Tuple[TradingAccount, str, str]:
    """(account, main private key shown ONCE, backup warning). The account exists
    even if the agent approval fails (a new wallet has no deposit yet)."""
    main = Account.create()
    main_key = "0x" + bytes(main.key).hex()
    address = main.address.lower()
    acct = TradingAccount(id=store.new_id(), label=label, kind=AccountKind.created, address=address,
                          agent_status=AgentStatus.missing, created_ms=now_ms(), has_main_key=True)
    with fsio.locked():
        doc = store.load()
        store.write_main_key(acct.id, address, main_key, passphrase)
        store.put_row(doc, acct)
        store.save(doc)
    note = ""
    try:
        acct = approve_with_main_key(acct, main_key)
    except VaultError as exc:
        note = f" Trading agent not approved yet: {exc}"
    return acct, main_key, BACKUP_WARNING + note


def import_api_key(label: str, main_address: str, agent_private_key: str) -> TradingAccount:
    main = norm_address(main_address, "main_address")
    key, agent_addr = key_to_address(agent_private_key)
    if agent_addr == main:
        raise MainKeyRefused(MAIN_KEY_REFUSED.format(main=main))
    rows = agents.lookup(main, force=True)
    if rows is None:
        raise HlUnavailable("could not verify the API wallet with Hyperliquid; try again")
    status, vu = agents.classify(agent_addr, rows, None, now_ms())
    if status == AgentStatus.missing:
        raise InvalidRequest(f"{agent_addr} is not an approved API wallet of {main}. "
                             f"Approve it at https://app.hyperliquid.xyz/API first.")
    if status == AgentStatus.expired:
        raise InvalidRequest(f"the API wallet {agent_addr} has expired; approve a new one")
    name = (agents.find_agent(rows, agent_addr) or {}).get("name") or ""
    return save_agent(label, AccountKind.connected_key, main, agent_addr, key, name, vu, status)


def prepare_agent_approval(main_address: str, agent_address: str, agent_name: str = "copycat") -> Dict[str, Any]:
    main = norm_address(main_address, "main_address")
    agent = norm_address(agent_address, "agent_address")
    if agent == main:
        raise MainKeyRefused("agent_address must be a NEW key generated in the browser, not your main wallet")
    if not _NAME_RE.match(agent_name or ""):
        raise InvalidRequest("agent_name: up to 16 letters, digits, space, _ or -")
    nonce = now_ms()
    action = hlops.approve_agent_action(agent, agent_name or "", nonce)
    return {"typed_data": hlops.approve_agent_typed_data(action), "action": action, "nonce": nonce}


def _check_action(action: Any, nonce: int, agent_addr: str) -> Dict[str, Any]:
    if not isinstance(action, dict) or set(action) != _ACTION_KEYS:
        raise InvalidRequest(f"action must have exactly the keys {sorted(_ACTION_KEYS)}")
    if action["type"] != "approveAgent":
        raise InvalidRequest("action.type must be approveAgent")
    if action["hyperliquidChain"] != hlops.hyperliquid_chain():
        raise InvalidRequest(f"action.hyperliquidChain must be {hlops.hyperliquid_chain()}")
    if not isinstance(action["signatureChainId"], str) or not _CHAIN_RE.match(action["signatureChainId"]):
        raise InvalidRequest("action.signatureChainId must be a 0x hex chain id")
    if not isinstance(action["agentName"], str) or not _NAME_RE.match(action["agentName"]):
        raise InvalidRequest("action.agentName: up to 16 letters, digits, space, _ or -")
    if str(action["agentAddress"]).lower() != agent_addr:
        raise InvalidRequest("agent_private_key does not belong to the agentAddress that was signed")
    if not isinstance(action["nonce"], int) or action["nonce"] != nonce:
        raise InvalidRequest("action.nonce must equal nonce")
    now = now_ms()
    if not (now - NONCE_MAX_AGE_MS <= nonce <= now + 60_000):
        raise InvalidRequest("this approval request expired; start the sign-in again")
    return action


def submit_agent_approval(label: str, main_address: str, agent_private_key: str, action: Any,
                          nonce: int, signature: str) -> TradingAccount:
    main = norm_address(main_address, "main_address")
    key, agent_addr = key_to_address(agent_private_key)
    if agent_addr == main:
        raise MainKeyRefused(MAIN_KEY_REFUSED.format(main=main))
    action = _check_action(action, nonce, agent_addr)
    canonical = hlops.approve_agent_action(agent_addr, action["agentName"], nonce,
                                           chain_id=action["signatureChainId"])
    typed = hlops.approve_agent_typed_data(canonical)
    try:
        sig = hlops.split_signature(str(signature))
    except ValueError:
        raise InvalidRequest("signature must be 0x + 65 bytes hex (r||s||v)") from None
    try:
        signer: Optional[str] = hlops.recover_typed_signer(typed, sig).lower()
    except Exception:
        signer = None
    if signer != main:
        raise SignatureMismatch(f"the signature was not made by {main}. Sign with the wallet you are connecting.")
    require_ok(hlops.post_signed_action(canonical, nonce, sig), main)
    status, vu, _ = confirm_agent(main, agent_addr)
    return save_agent(label, AccountKind.connected_signed, main, agent_addr, key, action["agentName"], vu, status)
