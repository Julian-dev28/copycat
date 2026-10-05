"""vault.public: the only names other services import from services/vault.

The vault is the single owner of secrets ($COPYCAT_DATA_DIR/vault/). See
services/vault/README.md for the storage layout and the threat model.

  create_account(label, passphrase) -> (TradingAccount, main_private_key, backup_warning)
  import_api_key(label, main_address, agent_private_key) -> TradingAccount
  import_env(main_address, agent_private_key) -> TradingAccount     ("Main (from .env)")
  prepare_agent_approval(main_address, agent_address, agent_name) -> {typed_data, action, nonce}
  submit_agent_approval(label, main_address, agent_private_key, action, nonce, signature) -> TradingAccount
  list_accounts(refresh_status=True) / get_account(id)
  set_active(id) / rename(id, label) / remove(id)
  refresh_agent(id, passphrase=None) -> TradingAccount
  transfer(from_id, to_address, amount_usd, passphrase, max_usd) -> {ok, from_address, to_address, amount_usd}
  prepare_user_action(id, kind, amount_usd, max_usd, to_perp, destination, confirm_destination, unified)
      -> {typed_data, action, nonce}                      (browser path: usdClassTransfer / usdSend / withdraw3)
  submit_user_action(id, kind, action, nonce, signature, max_usd, confirm_destination, unified) -> UserActionResult
  run_user_action(id, kind, amount_usd, max_usd, passphrase, to_perp, destination, confirm_destination, unified)
      -> UserActionResult                                 (passphrase path, created accounts)
  audit_log(limit) -> recent vault/audit.jsonl lines (no secrets)
  exists() / is_authoritative() / active_address() / active_credentials()   (hl.env, engine)

Errors are vault.errors.VaultError subclasses; each carries `http_status` and a
message that never contains a secret.
"""
from __future__ import annotations

from contracts.models import TradingAccount

from . import errors
from .audit import read as audit_log
from .funding import prepare_user_action, run_user_action, submit_user_action
from .manage import (
    active_address,
    active_credentials,
    get_account,
    is_authoritative,
    list_accounts,
    refresh_agent,
    remove,
    rename,
    set_active,
    transfer,
)
from .onboarding import (
    create_account,
    import_api_key,
    prepare_agent_approval,
    submit_agent_approval,
)
from .store import exists

ENV_LABEL = "Main (from .env)"


def import_env(main_address: str, agent_private_key: str) -> TradingAccount:
    """Migration from .env: import COPYCAT_ACCOUNT_ADDRESS + COPYCAT_AGENT_KEY as a
    connected_key account and activate it when nothing is active yet (same wallet,
    same key: trading continues exactly as before, now owned by the vault)."""
    acct = import_api_key(ENV_LABEL, main_address, agent_private_key)
    if active_address() is None:
        acct = set_active(acct.id)
    return acct


__all__ = [
    "create_account", "import_api_key", "import_env", "prepare_agent_approval", "submit_agent_approval",
    "list_accounts", "get_account", "set_active", "rename", "remove", "refresh_agent", "transfer",
    "prepare_user_action", "submit_user_action", "run_user_action", "audit_log",
    "exists", "is_authoritative", "active_address", "active_credentials", "errors", "ENV_LABEL",
]
