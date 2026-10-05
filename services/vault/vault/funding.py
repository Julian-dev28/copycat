"""Moving money: usdClassTransfer (spot <-> perps), usdSend, withdraw3.

All three are user-signed Hyperliquid actions: only the account's MAIN key can
sign them (an agent key cannot). Two signing paths:

  browser    (connected accounts) prepare_user_action -> the wallet signs the
             typed data -> submit_user_action recovers the signer, requires it
             to be the account address, re-checks every guard and posts.
  passphrase (created accounts)   run_user_action unlocks the main key and signs
             through the SDK's own sign_* function.

Guards (both paths, re-checked at submit because the browser holds the action
in between):
  - amount > 0 and <= `max_usd`, the live maximum the caller read from HL
    (withdraw also > the $1 fee: below it nothing would arrive)
  - usd_send: destination is another account in this vault (same rule as
    `transfer`): a stolen api token cannot send funds outside
  - withdraw: destination defaults to the account's own address; any other
    address needs `confirm_destination` equal to it
  - usd_class_transfer: `to_perp` required, no destination; refused on unified
    accounts (one balance, nothing to move)
Every attempt that reaches a guard is written to the audit log (vault/audit.py).
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from contracts.models import AccountKind, TradingAccount, UserActionKind

from . import audit, hlops, store
from .approval import norm_address, now_ms, require_ok
from .errors import HlRejected, HlUnavailable, InvalidRequest, SignatureMismatch, VaultError

NONCE_MAX_AGE_MS = 10 * 60 * 1000
WITHDRAW_FEE_USD = Decimal("1")
_AMOUNT_RE = re.compile(r"^\d{1,12}(\.\d{1,6})?$")
_CHAIN_RE = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
_SIG_RE = re.compile(r"^0x[0-9a-fA-F]{130}$")


def amount_str(amount_usd: Any) -> str:
    """USD -> HL's amount string: at most 6 decimals, rounded down, no exponent."""
    try:
        d = Decimal(str(amount_usd)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    except (InvalidOperation, ValueError):
        raise InvalidRequest("amount_usd is not a number") from None
    if not d.is_finite() or d <= 0:
        raise InvalidRequest("amount_usd must be > 0")
    out = format(d.normalize(), "f")
    return out


def _kind(kind: Any) -> str:
    try:
        return UserActionKind(kind).value
    except ValueError:
        raise InvalidRequest("kind must be usd_class_transfer, usd_send or withdraw") from None


def _check_amount(kind: str, amount: str, max_usd: Optional[float]) -> None:
    d = Decimal(amount)
    if max_usd is None:
        raise HlUnavailable("could not read this account's balance from Hyperliquid; try again")
    cap = Decimal(str(max_usd)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    if d > cap:
        raise InvalidRequest(f"amount {amount} is more than the {cap.normalize():f} USDC available for this")
    if kind == "withdraw" and d <= WITHDRAW_FEE_USD:
        raise InvalidRequest(f"a withdrawal must be more than the {WITHDRAW_FEE_USD} USDC fee")


def _check_destination(acct: TradingAccount, kind: str, to_perp: Optional[bool], destination: Optional[str],
                       confirm_destination: Optional[str], unified: bool) -> Tuple[Optional[bool], Optional[str]]:
    """(to_perp, destination) after the guards for this kind."""
    if kind == "usd_class_transfer":
        if destination:
            raise InvalidRequest("a spot <-> perps move has no destination")
        if not isinstance(to_perp, bool):
            raise InvalidRequest("to_perp is required (true: spot -> perps, false: perps -> spot)")
        if unified:
            raise InvalidRequest("this is a unified account: spot and perps share one USDC balance, "
                                 "there is nothing to move")
        return to_perp, None
    if to_perp is not None:
        raise InvalidRequest("to_perp only applies to usd_class_transfer")
    if kind == "usd_send":
        dest = norm_address(destination, "destination")
        if dest == acct.address:
            raise InvalidRequest("destination is this account")
        if store.find_by_address(store.load(), dest) is None:
            raise InvalidRequest("destination must be another account in this copycat")
        return None, dest
    dest = norm_address(destination, "destination") if destination else acct.address
    if dest != acct.address:
        confirm = str(confirm_destination or "").strip().lower()
        if confirm != dest:
            raise InvalidRequest("withdrawing to another address: type that address again in "
                                 "confirm_destination")
    return None, dest


def _guard(acct: TradingAccount, kind: str, amount_usd: Any, max_usd: Optional[float], to_perp: Optional[bool],
           destination: Optional[str], confirm_destination: Optional[str],
           unified: bool) -> Tuple[str, Optional[bool], Optional[str]]:
    amount = amount_str(amount_usd)
    to_perp, dest = _check_destination(acct, kind, to_perp, destination, confirm_destination, unified)
    _check_amount(kind, amount, max_usd)
    return amount, to_perp, dest


def _result(acct: TradingAccount, kind: str, amount: str, to_perp: Optional[bool], dest: Optional[str],
            nonce: int) -> Dict[str, Any]:
    msg = {"usd_class_transfer": f"Moved {amount} USDC {'spot -> perps' if to_perp else 'perps -> spot'}.",
           "usd_send": f"Sent {amount} USDC to {dest}.",
           "withdraw": f"Withdrawal of {amount} USDC to {dest} on Arbitrum requested "
                       f"(fee {WITHDRAW_FEE_USD} USDC, arrives in about 5 minutes)."}[kind]
    return {"ok": True, "kind": kind, "account_address": acct.address, "amount_usd": float(amount),
            "to_perp": to_perp, "destination": dest,
            "fee_usd": float(WITHDRAW_FEE_USD) if kind == "withdraw" else None, "nonce": nonce, "message": msg}


def _post(acct: TradingAccount, kind: str, path: str, amount: str, to_perp: Optional[bool], dest: Optional[str],
          action: Dict[str, Any], nonce: int, sig: Dict[str, Any]) -> Dict[str, Any]:
    entry = dict(kind=kind, path=path, account_id=acct.id, address=acct.address, amount=amount,
                 to_perp=to_perp, destination=dest, nonce=nonce)
    try:
        require_ok(hlops.post_signed_action(action, nonce, sig), acct.address)
    except HlRejected as exc:
        audit.record(outcome="rejected", reason=str(exc), **entry)
        raise
    except VaultError as exc:
        audit.record(outcome="error", reason=str(exc), **entry)
        raise
    audit.record(outcome="ok", reason=None, **entry)
    return _result(acct, kind, amount, to_perp, dest, nonce)


def _refuse(acct: Optional[TradingAccount], kind: str, path: str, exc: VaultError, **fields: Any) -> None:
    audit.record(outcome="refused", reason=str(exc), kind=kind, path=path,
                 account_id=acct.id if acct else None, address=acct.address if acct else None, **fields)


# ── browser path ───────────────────────────────────────────────────────────────

def prepare_user_action(account_id: str, kind: Any, amount_usd: Any, max_usd: Optional[float],
                        to_perp: Optional[bool] = None, destination: Optional[str] = None,
                        confirm_destination: Optional[str] = None, unified: bool = False) -> Dict[str, Any]:
    """{typed_data, action, nonce} for eth_signTypedData_v4. No side effect."""
    from .manage import get_account
    acct = get_account(account_id)
    kind = _kind(kind)
    amount, to_perp, dest = _guard(acct, kind, amount_usd, max_usd, to_perp, destination, confirm_destination,
                                   unified)
    nonce = now_ms()
    action = hlops.user_action(kind, amount, nonce, to_perp=to_perp, destination=dest)
    return {"typed_data": hlops.user_action_typed_data(kind, action), "action": action, "nonce": nonce}


def _parse_action(kind: str, action: Any, nonce: int) -> Tuple[str, Optional[bool], Optional[str], str]:
    """(amount, to_perp, destination, signatureChainId) from a submitted action, strictly."""
    if not isinstance(action, dict) or set(action) != hlops.user_action_keys(kind):
        raise InvalidRequest(f"action must have exactly the keys {sorted(hlops.user_action_keys(kind))}")
    expected_type = hlops.action_type(kind)
    if action["type"] != expected_type:
        raise InvalidRequest(f"action.type must be {expected_type}")
    if action["hyperliquidChain"] != hlops.hyperliquid_chain():
        raise InvalidRequest(f"action.hyperliquidChain must be {hlops.hyperliquid_chain()}")
    chain = action["signatureChainId"]
    if not isinstance(chain, str) or not _CHAIN_RE.match(chain):
        raise InvalidRequest("action.signatureChainId must be a 0x hex chain id")
    nonce_field = "nonce" if kind == "usd_class_transfer" else "time"
    if not isinstance(action[nonce_field], int) or isinstance(action[nonce_field], bool) \
            or action[nonce_field] != nonce:
        raise InvalidRequest(f"action.{nonce_field} must equal nonce")
    now = now_ms()
    if not (now - NONCE_MAX_AGE_MS <= nonce <= now + 60_000):
        raise InvalidRequest("this request expired; start again")
    amount = action["amount"]
    if not isinstance(amount, str) or not _AMOUNT_RE.match(amount) or amount_str(amount) != amount:
        raise InvalidRequest("action.amount must be a plain decimal string (at most 6 decimals)")
    if kind == "usd_class_transfer":
        if not isinstance(action["toPerp"], bool):
            raise InvalidRequest("action.toPerp must be true or false")
        return amount, action["toPerp"], None, chain
    if not isinstance(action["destination"], str):
        raise InvalidRequest("action.destination must be a 0x address")
    return amount, None, action["destination"], chain


def submit_user_action(account_id: str, kind: Any, action: Any, nonce: int, signature: str,
                       max_usd: Optional[float], confirm_destination: Optional[str] = None,
                       unified: bool = False) -> Dict[str, Any]:
    """Verify the browser-signed action (guards + signer == account address), post it."""
    from .manage import get_account
    acct = get_account(account_id)
    kind = _kind(kind)
    try:
        amount, to_perp, dest, chain = _parse_action(kind, action, nonce)
        amount, to_perp, dest = _guard(acct, kind, amount, max_usd, to_perp, dest, confirm_destination, unified)
        if not isinstance(signature, str) or not _SIG_RE.match(signature):
            raise InvalidRequest("signature must be 0x + 65 bytes hex (r||s||v)")
        canonical = hlops.user_action(kind, amount, nonce, to_perp=to_perp, destination=dest, chain_id=chain)
        sig = hlops.split_signature(signature)
        try:
            signer: Optional[str] = hlops.recover_typed_signer(hlops.user_action_typed_data(kind, canonical),
                                                               sig).lower()
        except Exception:
            signer = None
        if signer != acct.address:
            raise SignatureMismatch(f"the signature was not made by {acct.address}. Sign with that wallet.")
    except VaultError as exc:
        _refuse(acct, kind, "browser", exc, nonce=nonce)
        raise
    return _post(acct, kind, "browser", amount, to_perp, dest, canonical, nonce, sig)


# ── passphrase path ────────────────────────────────────────────────────────────

def run_user_action(account_id: str, kind: Any, amount_usd: Any, max_usd: Optional[float], passphrase: str,
                    to_perp: Optional[bool] = None, destination: Optional[str] = None,
                    confirm_destination: Optional[str] = None, unified: bool = False) -> Dict[str, Any]:
    """Created accounts: guards, unlock the main key, sign via the SDK, post."""
    from .manage import _unlock_main, get_account
    acct = get_account(account_id)
    kind = _kind(kind)
    try:
        if acct.kind != AccountKind.created or not acct.has_main_key:
            raise InvalidRequest("only a wallet copycat created can be signed with the passphrase; "
                                 "sign with your browser wallet instead")
        amount, to_perp, dest = _guard(acct, kind, amount_usd, max_usd, to_perp, destination,
                                       confirm_destination, unified)
        key = _unlock_main(acct, passphrase)
    except VaultError as exc:
        _refuse(acct, kind, "passphrase", exc)
        raise
    t = now_ms()
    action, sig = hlops.sign_user_action(key, kind, amount, t, to_perp=to_perp, destination=dest)
    del key
    return _post(acct, kind, "passphrase", amount, to_perp, dest, action, t, sig)
