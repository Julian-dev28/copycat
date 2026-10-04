"""vault/accounts.json (no secrets) and vault/keys/<id>.<purpose>.json (sealed).

accounts.json:
  {"version": 1,
   "active_id": "acc_..." | null,
   "authoritative": bool,      # set on the first activation, never cleared:
                               # from then on the vault, not .env, decides who trades
   "accounts": [TradingAccount without `active`]}

Secrets: `<id>.agent.json` (machine key) and `<id>.main.json` (passphrase, created
accounts only). Removing a created account moves its sealed main key to
vault/removed/ instead of deleting it: it may be the only copy of a wallet's key.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from contracts.models import TradingAccount

from . import crypto, fsio
from .errors import AccountNotFound, VaultCorrupt

ACCOUNTS_FILE = "accounts.json"
_ID_RE = re.compile(r"^acc_[0-9a-f]{16}$")
AGENT, MAIN = "agent", "main"


def accounts_path() -> Path:
    return fsio.vault_dir() / ACCOUNTS_FILE


def exists() -> bool:
    return accounts_path().exists()


def new_id() -> str:
    return "acc_" + secrets.token_hex(8)


def check_id(account_id: str) -> str:
    if not isinstance(account_id, str) or not _ID_RE.match(account_id):
        raise AccountNotFound(f"no account {account_id!r}")
    return account_id


def load() -> Dict[str, Any]:
    path = accounts_path()
    if not path.exists():
        return {"version": 1, "active_id": None, "authoritative": False, "accounts": []}
    try:
        doc = json.loads(fsio.read_private(path))
    except (OSError, ValueError) as exc:
        raise VaultCorrupt(f"{path} is unreadable") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), list):
        raise VaultCorrupt(f"{path} has an unexpected shape")
    doc.setdefault("active_id", None)
    doc.setdefault("authoritative", False)
    return doc


def save(doc: Dict[str, Any]) -> None:
    fsio.atomic_write(accounts_path(), (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())


def rows(doc: Dict[str, Any]) -> List[TradingAccount]:
    active = doc.get("active_id")
    return [TradingAccount.model_validate({**r, "active": r.get("id") == active}) for r in doc["accounts"]]


def find(doc: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    check_id(account_id)
    for r in doc["accounts"]:
        if r.get("id") == account_id:
            return r
    raise AccountNotFound(f"no account {account_id!r}")


def find_by_address(doc: Dict[str, Any], address: str) -> Optional[Dict[str, Any]]:
    a = address.lower()
    return next((r for r in doc["accounts"] if r.get("address") == a), None)


def put_row(doc: Dict[str, Any], acct: TradingAccount) -> None:
    data = acct.model_dump(mode="json", exclude={"active"})
    for i, r in enumerate(doc["accounts"]):
        if r.get("id") == acct.id:
            doc["accounts"][i] = data
            return
    doc["accounts"].append(data)


# ── sealed secrets ──────────────────────────────────────────────────────────

def _aad(account_id: str, purpose: str, address: str) -> bytes:
    return f"copycat/vault/v1/{account_id}/{purpose}/{address.lower()}".encode()


def _key_path(account_id: str, purpose: str, folder: str = "keys") -> Path:
    return fsio.vault_dir() / folder / f"{check_id(account_id)}.{purpose}.json"


def write_agent_key(account_id: str, agent_address: str, private_key: str) -> None:
    blob = crypto.seal_machine(private_key.encode(), _aad(account_id, AGENT, agent_address))
    blob["address"] = agent_address.lower()
    fsio.atomic_write(_key_path(account_id, AGENT), json.dumps(blob).encode())


def read_agent_key(account_id: str) -> Optional[str]:
    path = _key_path(account_id, AGENT)
    if not path.exists():
        return None
    blob = json.loads(fsio.read_private(path))
    return crypto.open_machine(blob, _aad(account_id, AGENT, blob.get("address", ""))).decode()


def write_main_key(account_id: str, address: str, private_key: str, passphrase: str) -> None:
    blob = crypto.seal_passphrase(private_key.encode(), passphrase, _aad(account_id, MAIN, address))
    fsio.atomic_write(_key_path(account_id, MAIN), json.dumps(blob).encode())


def read_main_key(account_id: str, address: str, passphrase: str) -> str:
    path = _key_path(account_id, MAIN)
    if not path.exists():
        raise AccountNotFound("this account has no stored main key")
    blob = json.loads(fsio.read_private(path))
    return crypto.open_passphrase(blob, passphrase, _aad(account_id, MAIN, address)).decode()


def delete_agent_key(account_id: str) -> None:
    _key_path(account_id, AGENT).unlink(missing_ok=True)


def archive_main_key(account_id: str) -> None:
    src = _key_path(account_id, MAIN)
    if src.exists():
        dst = _key_path(account_id, MAIN, folder="removed")
        fsio.ensure_dir(dst.parent)
        src.replace(dst)
