"""Funding a trading account: deposit facts, and the three user-signed money
actions (usdClassTransfer spot<->perps, usdSend, withdraw3).

  GET  /api/accounts/{id}/funding-info     FundingInfo (bridge, USDC, minimum, fee, live limits)
  POST /api/accounts/{id}/action/prepare   UserActionPrepareRequest -> UserActionPrepareResponse
  POST /api/accounts/{id}/action/submit    UserActionSubmitRequest -> UserActionResult (browser-signed)
  POST /api/accounts/{id}/action           UserActionRunRequest -> UserActionResult (passphrase, created)

Every money route reads the live limits first (502 when the read fails) and the
vault enforces them, plus the destination rules (services/vault/vault/funding.py).
submit and the passphrase route are rate-limited like the other secret routes
(5/min, 30/h per action kind). services/mcp never calls any of this.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

from contracts.models import (
    FundingInfo,
    FundingLimits,
    TradingAccount,
    UserActionPrepareRequest,
    UserActionPrepareResponse,
    UserActionResult,
    UserActionRunRequest,
    UserActionSubmitRequest,
)

from .. import funding
from ..accounts_backend import AccountsBackend
from ..attempt_limit import AttemptLimiter
from ..deps import require_auth
from .accounts_common import PREFIX, get_accounts_backend, get_attempt_limiter, vault_call

router = APIRouter(prefix=PREFIX, tags=["accounts"], dependencies=[Depends(require_auth)])


def _read(backend: AccountsBackend, account_id: str) -> Tuple[TradingAccount, Optional[FundingLimits]]:
    acct = vault_call(backend.vault().get_account, account_id)
    return acct, funding.limits(backend.account_state(acct.address), backend.spot_balances(acct.address))


def _live(backend: AccountsBackend, account_id: str) -> Tuple[TradingAccount, FundingLimits]:
    acct, lim = _read(backend, account_id)
    if lim is None:
        raise HTTPException(502, "could not read this account's balances from Hyperliquid; try again")
    return acct, lim


@router.get("/{account_id}/funding-info", response_model=FundingInfo)
def funding_info(account_id: str, backend: AccountsBackend = Depends(get_accounts_backend)) -> FundingInfo:
    acct, lim = _read(backend, account_id)
    return funding.info(acct, backend.funding_facts(), lim)


@router.post("/{account_id}/action/prepare", response_model=UserActionPrepareResponse)
def action_prepare(account_id: str, body: UserActionPrepareRequest,
                   backend: AccountsBackend = Depends(get_accounts_backend)) -> UserActionPrepareResponse:
    _, lim = _live(backend, account_id)
    out = vault_call(backend.vault().prepare_user_action, account_id, body.kind.value, body.amount_usd,
                     funding.cap_for(lim, body.kind.value, body.to_perp), to_perp=body.to_perp,
                     destination=body.destination, confirm_destination=body.confirm_destination,
                     unified=lim.unified)
    return UserActionPrepareResponse(**out)


@router.post("/{account_id}/action/submit", response_model=UserActionResult)
def action_submit(account_id: str, body: UserActionSubmitRequest,
                  backend: AccountsBackend = Depends(get_accounts_backend),
                  limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> UserActionResult:
    limiter.check(f"action-{body.kind.value}")
    _, lim = _live(backend, account_id)
    to_perp: Any = body.action.get("toPerp") if isinstance(body.action, dict) else None
    out = vault_call(backend.vault().submit_user_action, account_id, body.kind.value, body.action, body.nonce,
                     body.signature, funding.cap_for(lim, body.kind.value, to_perp),
                     confirm_destination=body.confirm_destination, unified=lim.unified)
    return UserActionResult(**out)


@router.post("/{account_id}/action", response_model=UserActionResult)
def action_run(account_id: str, body: UserActionRunRequest,
               backend: AccountsBackend = Depends(get_accounts_backend),
               limiter: AttemptLimiter = Depends(get_attempt_limiter)) -> UserActionResult:
    limiter.check(f"action-{body.kind.value}")
    _, lim = _live(backend, account_id)
    out = vault_call(backend.vault().run_user_action, account_id, body.kind.value, body.amount_usd,
                     funding.cap_for(lim, body.kind.value, body.to_perp), body.passphrase, to_perp=body.to_perp,
                     destination=body.destination, confirm_destination=body.confirm_destination,
                     unified=lim.unified)
    return UserActionResult(**out)
