"""Pure helpers for the funding routes: live limits from hl reads, the cap
that applies to one action, and the static FundingInfo notes.

Limits come from two reads the Account page already makes (account_state,
spotClearinghouseState). Non-unified accounts: usdSend / withdraw3 / perps->spot
draw from the main perp dex's `withdrawable`; spot->perps from spot USDC
total - hold. Unified accounts (unifiedAccount, portfolioMargin): hl.venue
already reports `available` as spot USDC free, and there is nothing to move.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts.models import AccountKind, FundingInfo, FundingLimits, TradingAccount

UNIFIED = ("unifiedAccount", "portfolioMargin")


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def limits(state: Optional[Dict[str, Any]], spot: Optional[List[Dict[str, Any]]]) -> Optional[FundingLimits]:
    """None when either read failed: a partial read must never look like $0 (or like money)."""
    if state is None or spot is None:
        return None
    abstraction = state.get("abstraction")
    unified = abstraction in UNIFIED
    perp = _f((state.get("available") or {}).get(""))
    spot_free = sum(_f(b.get("total")) - _f(b.get("hold")) for b in spot if b.get("coin") == "USDC")
    return FundingLimits(abstraction=abstraction, unified=unified,
                         perps_withdrawable_usd=round(max(perp, 0.0), 6),
                         spot_usdc_free_usd=round(max(spot_free, 0.0), 6))


def cap_for(lim: Optional[FundingLimits], kind: str, to_perp: Any) -> Optional[float]:
    if lim is None:
        return None
    if kind == "usd_class_transfer" and to_perp is True:
        return lim.spot_usdc_free_usd
    return lim.perps_withdrawable_usd


def signer_for(acct: TradingAccount) -> str:
    return "passphrase" if acct.kind == AccountKind.created and acct.has_main_key else "browser"


def info(acct: TradingAccount, facts: Dict[str, Any], lim: Optional[FundingLimits]) -> FundingInfo:
    min_dep, fee = facts["min_deposit_usd"], facts["withdraw_fee_usd"]
    notes = [
        f"Deposit: send native USDC on {facts['chain_name']} to the Hyperliquid bridge FROM {acct.address}. "
        f"The bridge credits the address that sent it, in under a minute.",
        f"Minimum deposit {min_dep:g} USDC: Hyperliquid's docs say a smaller deposit is never credited and is lost.",
        "Never send USDC on Arbitrum straight to this address: it stays on Arbitrum.",
        f"Withdrawals go to Arbitrum, cost {fee:g} USDC and arrive in about 5 minutes.",
        "Hyperliquid's docs call this bridge 'legacy' and prefer Circle CCTP; the bridge still credits deposits.",
    ]
    if lim is not None and lim.unified:
        notes.append("Unified account: spot and perps share one USDC balance, no spot/perps move needed.")
    return FundingInfo(network=facts["network"], chain_id=facts["chain_id"], chain_name=facts["chain_name"],
                       usdc_address=facts["usdc_address"], bridge_address=facts["bridge_address"],
                       explorer_url=facts["explorer_url"], min_deposit_usd=min_dep, withdraw_fee_usd=fee,
                       account_address=acct.address, account_kind=acct.kind, signer=signer_for(acct),
                       limits=lim, source_url=facts["source_url"], notes=notes)
