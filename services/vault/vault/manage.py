"""Day-to-day account operations and the engine's credential read."""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, List, Optional, Tuple

from eth_account import Account

from contracts.models import AccountKind, TradingAccount

from . import agents, fsio, hlops, store
from .approval import approve_with_main_key, norm_address, now_ms, require_ok
from .errors import InvalidRequest, NeedsBrowserSignIn, VaultCorrupt, WrongPassphrase

logger = logging.getLogger(__name__)


def is_authoritative() -> bool:
    """True once any account has been activated. Before that, .env still trades."""
    return store.exists() and bool(store.load().get("authoritative"))


def list_accounts(refresh_status: bool = True) -> List[TradingAccount]:
    """Every account, agent status from extraAgents (cached 10 min per address)."""
    doc = store.load()
    if not refresh_status:
        return store.rows(doc)
    now = now_ms()
    updates: Dict[str, Dict[str, Any]] = {}
    for r in doc["accounts"]:
        rows = agents.lookup(r["address"]) if r.get("agent_address") else None
        st, vu = agents.classify(r.get("agent_address"), rows, r.get("agent_valid_until_ms"), now)
        if st.value != r.get("agent_status") or vu != r.get("agent_valid_until_ms"):
            updates[r["id"]] = {"agent_status": st.value, "agent_valid_until_ms": vu}
    if updates:
        with fsio.locked():
            doc = store.load()
            for r in doc["accounts"]:
                r.update(updates.get(r["id"], {}))
            store.save(doc)
    return store.rows(doc)


def get_account(account_id: str) -> TradingAccount:
    doc = store.load()
    row = store.find(doc, account_id)
    return TradingAccount.model_validate({**row, "active": doc.get("active_id") == account_id})


def set_active(account_id: str) -> TradingAccount:
    with fsio.locked():
        doc = store.load()
        store.find(doc, account_id)
        prev = doc.get("active_id")
        doc["active_id"] = account_id
        doc["authoritative"] = True
        store.save(doc)
    if prev != account_id:
        logger.info("[vault] active trading account %s -> %s", prev, account_id)
    return get_account(account_id)


def rename(account_id: str, label: str) -> TradingAccount:
    with fsio.locked():
        doc = store.load()
        row = store.find(doc, account_id)
        row["label"] = TradingAccount.model_validate({**row, "label": label}).label
        store.save(doc)
    return get_account(account_id)


def remove(account_id: str) -> None:
    """Forget an account. Removing the active one stops trading (it never falls
    back to .env). Its agent key is deleted; a created wallet's sealed main key
    is archived to vault/removed/, never destroyed."""
    with fsio.locked():
        doc = store.load()
        row = store.find(doc, account_id)
        doc["accounts"] = [r for r in doc["accounts"] if r["id"] != account_id]
        if doc.get("active_id") == account_id:
            doc["active_id"] = None
            logger.warning("[vault] removed the ACTIVE account %s: trading is off until another is activated",
                           account_id)
        store.save(doc)
        store.delete_agent_key(account_id)
        store.archive_main_key(account_id)
    agents.invalidate(row["address"])


def _unlock_main(acct: TradingAccount, passphrase: Optional[str]) -> str:
    if not passphrase:
        raise WrongPassphrase()
    key = store.read_main_key(acct.id, acct.address, passphrase)
    if Account.from_key(key).address.lower() != acct.address:
        raise VaultCorrupt("stored main key does not match its account")
    return key


def refresh_agent(account_id: str, passphrase: Optional[str] = None) -> TradingAccount:
    acct = get_account(account_id)
    if acct.kind != AccountKind.created:
        raise NeedsBrowserSignIn("re-run sign-in: connect this wallet again (sign with your wallet, or paste "
                                 "a new API wallet key) to renew its trading agent")
    return approve_with_main_key(acct, _unlock_main(acct, passphrase))


def _amount_str(amount_usd: float) -> str:
    d = Decimal(str(amount_usd)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    if d <= 0:
        raise InvalidRequest("amount_usd must be > 0")
    return format(d.normalize(), "f")


def transfer(from_id: str, to_address: str, amount_usd: float, passphrase: str) -> Dict[str, Any]:
    """usdSend (perps USDC) from a created account to another account in this vault."""
    src = get_account(from_id)
    if src.kind != AccountKind.created or not src.has_main_key:
        raise InvalidRequest("transfers can only be sent from a wallet copycat created (it holds that key)")
    dest = norm_address(to_address, "to_address")
    if dest == src.address:
        raise InvalidRequest("to_address is the source account")
    if store.find_by_address(store.load(), dest) is None:
        raise InvalidRequest("to_address must be another account in this copycat")
    amount = _amount_str(amount_usd)
    key = _unlock_main(src, passphrase)
    t = now_ms()
    action, sig = hlops.sign_usd_send(key, dest, amount, t)
    del key
    require_ok(hlops.post_signed_action(action, t, sig), src.address)
    logger.info("[vault] usdSend %s USDC %s -> %s", amount, src.address, dest)
    return {"ok": True, "from_address": src.address, "to_address": dest, "amount_usd": float(amount)}


def active_address() -> Optional[str]:
    doc = store.load()
    aid = doc.get("active_id")
    row = next((r for r in doc["accounts"] if r["id"] == aid), None) if aid else None
    return row["address"] if row else None


def active_credentials() -> Optional[Tuple[str, str]]:
    """(main address, agent private key) of the active account, or None."""
    doc = store.load()
    aid = doc.get("active_id")
    row = next((r for r in doc["accounts"] if r["id"] == aid), None) if aid else None
    if not row or not row.get("agent_address"):
        return None
    key = store.read_agent_key(aid)
    if not key:
        return None
    if Account.from_key(key).address.lower() != row["agent_address"]:
        raise VaultCorrupt("stored agent key does not match its account")
    return row["address"], key
