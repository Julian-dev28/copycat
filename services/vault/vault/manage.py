"""Day-to-day account operations and the engine's credential read."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from eth_account import Account

from contracts.models import AccountKind, TradingAccount

from . import agents, crypto, fsio, guess_guard, store
from .approval import approve_with_main_key, now_ms
from .errors import NeedsBrowserSignIn, VaultCorrupt, WrongPassphrase

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
    """The ONE place a created wallet's main key is decrypted. Audit M6: a
    persisted per-account guard refuses while locked out and counts wrong
    passphrases; audit M7: a blob sealed at weaker scrypt params is re-sealed
    at the current ones after a successful unlock."""
    guess_guard.check(acct.id)
    if not passphrase:
        raise WrongPassphrase()
    try:
        key = store.read_main_key(acct.id, acct.address, passphrase)
    except WrongPassphrase:
        guess_guard.failed(acct.id)
        raise
    if Account.from_key(key).address.lower() != acct.address:
        raise VaultCorrupt("stored main key does not match its account")
    guess_guard.succeeded(acct.id)
    n = store.main_key_scrypt_n(acct.id)
    if n is not None and n < crypto.SCRYPT_N:
        with fsio.locked():
            store.write_main_key(acct.id, acct.address, key, passphrase)
        logger.info("[vault] re-sealed account %s main key at scrypt N=%d", acct.id, crypto.SCRYPT_N)
    return key


def refresh_agent(account_id: str, passphrase: Optional[str] = None) -> TradingAccount:
    acct = get_account(account_id)
    if acct.kind != AccountKind.created:
        raise NeedsBrowserSignIn("re-run sign-in: connect this wallet again (sign with your wallet, or paste "
                                 "a new API wallet key) to renew its trading agent")
    return approve_with_main_key(acct, _unlock_main(acct, passphrase))


def transfer(from_id: str, to_address: str, amount_usd: float, passphrase: str,
             max_usd: Optional[float] = None) -> Dict[str, Any]:
    """usdSend (perps USDC) from a created account to another account in this vault.
    Same guards and audit line as run_user_action(kind=usd_send); `max_usd` is the
    live perps withdrawable the caller read (None: refused, the balance is unknown)."""
    from .funding import run_user_action
    out = run_user_action(from_id, "usd_send", amount_usd, max_usd, passphrase, destination=to_address)
    return {"ok": True, "from_address": out["account_address"], "to_address": out["destination"],
            "amount_usd": out["amount_usd"]}


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
    key = store.read_agent_key(aid, row["agent_address"])
    if not key:
        return None
    if Account.from_key(key).address.lower() != row["agent_address"]:
        raise VaultCorrupt("stored agent key does not match its account")
    return row["address"], key
