"""Managing trading accounts.

  GET    /api/accounts                       TradingAccount[] (agent status, cached 10 min)
  POST   /api/accounts/{id}/activate?force=  TradingAccount. 409 while the current active
                                             account still has engine copies open (they would
                                             stop being managed), unless force=true
  PATCH  /api/accounts/{id}                  {label} -> TradingAccount
  DELETE /api/accounts/{id}                  {ok}. Removing the active account stops trading
  POST   /api/accounts/{id}/refresh-agent    RefreshAgentRequest -> TradingAccount
  POST   /api/accounts/transfer              TransferRequest -> TransferResult (usdSend)
  GET    /api/accounts/{id}/summary          AccountSummary
  GET    /api/accounts/{id}/history?kind=    AccountHistory
"""
from __future__ import annotations

import time
from typing import Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException

from contracts.models import AccountSummary, RefreshAgentRequest, TradingAccount, TransferRequest

from .. import account_history as H
from .. import account_summary
from ..account_schemas import AccountHistory, LabelPatch, TransferResult
from ..accounts_backend import AccountsBackend
from ..attempt_limit import AttemptLimiter
from ..deps import require_auth
from .accounts_common import PREFIX, get_accounts_backend, get_attempt_limiter, vault_call

router = APIRouter(prefix=PREFIX, tags=["accounts"], dependencies=[Depends(require_auth)])


@router.get("", response_model=List[TradingAccount])
def list_accounts(backend: AccountsBackend = Depends(get_accounts_backend)) -> List[TradingAccount]:
    vault = backend.vault()
    return vault_call(vault.list_accounts) if vault.exists() else []


@router.post("/transfer", response_model=TransferResult)
def transfer(body: TransferRequest, backend: AccountsBackend = Depends(get_accounts_backend),
             limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> TransferResult:
    limiter.check("transfer")
    out = vault_call(backend.vault().transfer, body.from_account_id, body.to_address, body.amount_usd,
                     body.passphrase)
    return TransferResult(**out)


@router.post("/{account_id}/activate", response_model=TradingAccount)
def activate(account_id: str, force: bool = False,
             backend: AccountsBackend = Depends(get_accounts_backend)) -> TradingAccount:
    vault = backend.vault()
    target = vault_call(vault.get_account, account_id)
    current = vault.active_address()
    if current and current != target.address and not force:
        st = backend.engine_status(current)
        n = len(st.positions) if st is not None else 0
        if n:
            raise HTTPException(409, f"{current} still has {n} copies open. Close them first (Close all), "
                                     f"or activate with force=true to leave them unmanaged.")
    return vault_call(vault.set_active, account_id)


@router.patch("/{account_id}", response_model=TradingAccount)
def rename(account_id: str, body: LabelPatch,
           backend: AccountsBackend = Depends(get_accounts_backend)) -> TradingAccount:
    return vault_call(backend.vault().rename, account_id, body.label)


@router.delete("/{account_id}")
def remove(account_id: str, backend: AccountsBackend = Depends(get_accounts_backend)) -> Dict[str, bool]:
    vault_call(backend.vault().remove, account_id)
    return {"ok": True}


@router.post("/{account_id}/refresh-agent", response_model=TradingAccount)
def refresh_agent(account_id: str, body: RefreshAgentRequest,
                  backend: AccountsBackend = Depends(get_accounts_backend),
                  limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> TradingAccount:
    limiter.check("refresh")
    return vault_call(backend.vault().refresh_agent, account_id, body.passphrase)


@router.get("/{account_id}/summary", response_model=AccountSummary)
def summary(account_id: str, backend: AccountsBackend = Depends(get_accounts_backend)) -> AccountSummary:
    acct = vault_call(backend.vault().get_account, account_id)
    state = backend.account_state(acct.address)
    if state is None:
        raise HTTPException(502, "Hyperliquid account read failed; try again")
    return account_summary.build(acct, state, backend.extras(acct.address), backend.portfolio(acct.address),
                                 backend.engine_status(acct.address), backend.metrics(acct.address),
                                 int(time.time() * 1000))


@router.get("/{account_id}/history", response_model=AccountHistory)
def history(account_id: str, kind: Literal["fills", "orders", "transfers", "balances"],
            backend: AccountsBackend = Depends(get_accounts_backend)) -> AccountHistory:
    addr = vault_call(backend.vault().get_account, account_id).address
    if kind == "fills":
        raw, shape = backend.fills(addr), H.fills
    elif kind == "orders":
        raw, shape = backend.historical_orders(addr), H.orders
    elif kind == "transfers":
        raw, shape = backend.ledger_updates(addr), H.transfers
    else:
        raw = backend.spot_balances(addr)
        if raw is None:
            raise HTTPException(502, "Hyperliquid read failed; try again")
        return AccountHistory(kind=kind, rows=H.balances(raw, backend.account_state(addr)))
    if raw is None:
        raise HTTPException(502, "Hyperliquid read failed; try again")
    return AccountHistory(kind=kind, rows=shape(raw))
