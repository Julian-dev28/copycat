"""Adding trading accounts.

  POST /api/accounts/create            CreateAccountRequest -> CreateAccountResponse (key shown once)
  POST /api/accounts/import-key        ImportApiKeyRequest -> TradingAccount
  GET  /api/accounts/import-env        ImportEnvStatus (is the .env migration available?)
  POST /api/accounts/import-env        -> TradingAccount[] (imports .env as "Main (from .env)")
  POST /api/accounts/approve/prepare   AgentApprovalPrepareRequest -> AgentApprovalPrepareResponse
  POST /api/accounts/approve/submit    AgentApprovalSubmitRequest -> TradingAccount

Sync handlers (threadpool): scrypt and HL calls never block the event loop.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from contracts.models import (
    AgentApprovalPrepareRequest,
    AgentApprovalPrepareResponse,
    AgentApprovalSubmitRequest,
    CreateAccountRequest,
    CreateAccountResponse,
    ImportApiKeyRequest,
    TradingAccount,
)

from ..account_schemas import ImportEnvStatus
from ..accounts_backend import AccountsBackend
from ..attempt_limit import AttemptLimiter
from ..deps import require_auth
from ..env_import import env_credentials
from .accounts_common import PREFIX, get_accounts_backend, get_attempt_limiter, vault_call

router = APIRouter(prefix=PREFIX, tags=["accounts"], dependencies=[Depends(require_auth)])


@router.post("/create", response_model=CreateAccountResponse)
def create(body: CreateAccountRequest, backend: AccountsBackend = Depends(get_accounts_backend),
           limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> CreateAccountResponse:
    limiter.check("create")
    acct, key, warning = vault_call(backend.vault().create_account, body.label, body.passphrase)
    return CreateAccountResponse(account=acct, private_key=key, backup_warning=warning)


@router.post("/import-key", response_model=TradingAccount)
def import_key(body: ImportApiKeyRequest, backend: AccountsBackend = Depends(get_accounts_backend),
               limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> TradingAccount:
    limiter.check("import")
    return vault_call(backend.vault().import_api_key, body.label, body.main_address, body.agent_private_key)


@router.get("/import-env", response_model=ImportEnvStatus)
def import_env_status(backend: AccountsBackend = Depends(get_accounts_backend)) -> ImportEnvStatus:
    address, key = env_credentials()
    del key
    if not address:
        return ImportEnvStatus(available=False, reason="no COPYCAT_ACCOUNT_ADDRESS/COPYCAT_AGENT_KEY in .env")
    vault = backend.vault()
    known = vault.exists() and any(a.address == address.lower()
                                   for a in vault.list_accounts(refresh_status=False))
    if known:
        return ImportEnvStatus(available=False, address=address.lower(), reason="already in the vault")
    return ImportEnvStatus(available=True, address=address.lower())


@router.post("/import-env", response_model=List[TradingAccount])
def import_env(backend: AccountsBackend = Depends(get_accounts_backend),
               limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> List[TradingAccount]:
    limiter.check("import")
    address, key = env_credentials()
    if not (address and key):
        raise HTTPException(404, "no COPYCAT_ACCOUNT_ADDRESS + COPYCAT_AGENT_KEY found in .env")
    vault = backend.vault()
    vault_call(vault.import_env, address, key)
    del key
    return vault.list_accounts(refresh_status=False)


@router.post("/approve/prepare", response_model=AgentApprovalPrepareResponse)
def approve_prepare(body: AgentApprovalPrepareRequest,
                    backend: AccountsBackend = Depends(get_accounts_backend)) -> AgentApprovalPrepareResponse:
    out = vault_call(backend.vault().prepare_agent_approval, body.main_address, body.agent_address,
                     body.agent_name)
    return AgentApprovalPrepareResponse(**out)


@router.post("/approve/submit", response_model=TradingAccount)
def approve_submit(body: AgentApprovalSubmitRequest, backend: AccountsBackend = Depends(get_accounts_backend),
                   limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> TradingAccount:
    limiter.check("submit")
    return vault_call(backend.vault().submit_agent_approval, body.label, body.main_address,
                      body.agent_private_key, body.action, body.nonce, body.signature)
