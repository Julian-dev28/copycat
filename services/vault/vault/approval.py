"""Shared steps of every agent approval: validate, post, confirm, store."""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, Optional, Tuple

from eth_account import Account

from contracts.models import AccountKind, AgentStatus, TradingAccount

from . import agents, fsio, hlops, store
from .errors import FUND_FIRST, HlRejected, HlUnavailable, InvalidRequest, NeedsFunding

logger = logging.getLogger(__name__)

AGENT_NAME = "copycat"
CONFIRM_TRIES = 5
CONFIRM_SLEEP_S = 1.0
_ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")
_UNFUNDED = ("does not exist", "must deposit", "deposit before")
_sleep = time.sleep


def now_ms() -> int:
    return int(time.time() * 1000)


def norm_address(address: Any, what: str = "address") -> str:
    a = str(address or "").strip().lower()
    if not _ADDR_RE.match(a):
        raise InvalidRequest(f"{what} is not a 0x address")
    return a


def key_to_address(private_key: Any) -> Tuple[str, str]:
    """(normalized 0x key, lowercase address). The error never echoes the key."""
    k = str(private_key or "").strip()
    k = k if k.startswith("0x") else "0x" + k
    try:
        addr = Account.from_key(k).address.lower()
    except Exception:
        raise InvalidRequest("not a valid private key (expected 64 hex characters)") from None
    return k, addr


def require_ok(resp: Dict[str, Any], main_address: str) -> None:
    if isinstance(resp, dict) and resp.get("status") == "ok":
        return
    text = str((resp or {}).get("response") or resp)[:300]
    if any(s in text.lower() for s in _UNFUNDED):
        raise NeedsFunding(FUND_FIRST.format(address=main_address))
    if (resp or {}).get("ambiguous"):
        raise HlUnavailable(f"Hyperliquid did not answer ({text}). Press Refresh agent to retry.")
    raise HlRejected(f"Hyperliquid rejected the request: {text}")


def confirm(main_address: str, agent_address: str) -> Tuple[AgentStatus, Optional[int], Optional[str]]:
    """Poll extraAgents until the new agent shows up (HL can lag a moment).
    (status, validUntil, name); unknown if it never appeared."""
    for i in range(CONFIRM_TRIES):
        rows = agents.lookup(main_address, force=True)
        hit = agents.find_agent(rows or [], agent_address)
        if hit is not None:
            st, vu = agents.classify(agent_address, rows, None, now_ms())
            return st, vu, hit.get("name")
        if i + 1 < CONFIRM_TRIES:
            _sleep(CONFIRM_SLEEP_S)
    logger.warning("[vault] HL accepted the approval for %s but extraAgents does not list agent %s yet",
                   main_address, agent_address)
    return AgentStatus.unknown, None, None


def save_agent(label: str, kind: AccountKind, main_address: str, agent_address: str, agent_key: str,
               agent_name: str, valid_until: Optional[int], status: AgentStatus,
               account_id: Optional[str] = None) -> TradingAccount:
    """Upsert the one vault account for `main_address` with this agent. The new
    agent key overwrites the previous one: HL replaces a same-name agent, so the
    old key is dead anyway."""
    with fsio.locked():
        doc = store.load()
        row = store.find(doc, account_id) if account_id else store.find_by_address(doc, main_address)
        if row is not None and row.get("agent_address") and row["agent_address"] != agent_address:
            logger.info("[vault] account %s: agent %s replaced by %s", row["id"], row["agent_address"],
                        agent_address)
        acct_id = row["id"] if row else store.new_id()
        store.write_agent_key(acct_id, agent_address, agent_key)
        acct = TradingAccount(
            id=acct_id, label=label if label else (row or {}).get("label", "Account"),
            kind=AccountKind.created if row and row.get("kind") == "created" else kind,
            address=main_address, agent_address=agent_address, agent_name=agent_name,
            agent_valid_until_ms=valid_until, agent_status=status,
            created_ms=(row or {}).get("created_ms") or now_ms(),
            has_main_key=bool((row or {}).get("has_main_key")))
        store.put_row(doc, acct)
        store.save(doc)
        active = doc.get("active_id") == acct_id
    agents.invalidate(main_address)
    return acct.model_copy(update={"active": active})


def approve_with_main_key(acct: TradingAccount, main_key: str) -> TradingAccount:
    """Created accounts: a fresh agent, approveAgent signed by the main key."""
    agent = Account.create()
    agent_key = "0x" + bytes(agent.key).hex()
    agent_addr = agent.address.lower()
    nonce = now_ms()
    action, sig = hlops.sign_approve_agent(main_key, agent_addr, AGENT_NAME, nonce)
    require_ok(hlops.post_signed_action(action, nonce, sig), acct.address)
    status, vu, _ = confirm(acct.address, agent_addr)
    return save_agent(acct.label, acct.kind, acct.address, agent_addr, agent_key, AGENT_NAME, vu, status,
                      account_id=acct.id)
