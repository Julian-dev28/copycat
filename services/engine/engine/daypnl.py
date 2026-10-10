"""Day PnL net of transfers. Pure: no venue, no state, same rows same answer.

    day PnL = equity now - equity at the UTC day anchor - net transfers since the anchor

`net_transfers` reads HL `userNonFundingLedgerUpdates` rows (hl.history.ledger_since)
and returns the USD that entered (+) or left (-) the account's equity for reasons
that are not trading. Equity here is `sizing.account_equity`: perp accountValue
over every dex read + spot USDC. So:

- deposit, vault withdraw / distribution / leader commission: money in.
- withdraw (+ its fee), vault deposit / create (+ fee): money out.
- internalTransfer, subAccountTransfer, send, spotTransfer: in when we are the
  destination, out (+ fee) when we are the sender, only the fee when both sides
  are us (a dex-to-dex move). `send` / `spotTransfer` count only USDC; other
  tokens are not in equity (a USDC fee the sender pays still is).
- accountClassTransfer (spot <-> perp): 0. Both sides are in equity.
- liquidation, spotGenesis, cStakingTransfer: not transfers (a liquidation is
  trading PnL; the others move tokens equity does not count).

Anything else, a row we cannot read, or a row inside the ambiguity window
around the account read (the equity read may or may not include it) makes the
result unreliable: `problem` is set and the caller must not use the number.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# A ledger row this close to the account read may or may not be in that read's
# equity (HL clock vs ours, and the ledger read lands a moment after the account
# read). Such a cycle is unreliable; the next one resolves it.
AMBIGUITY_MS = 15_000

IGNORED = frozenset({"liquidation", "spotGenesis", "cStakingTransfer"})
_IN = {"deposit": "usdc", "vaultDistribution": "usdc", "vaultLeaderCommission": "usdc"}
_PEER = frozenset({"internalTransfer", "subAccountTransfer", "send", "spotTransfer"})


def _f(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    return float(v)   # raises on garbage: the caller turns that into a problem


def delta_usd(delta: Dict[str, Any], our: str) -> Optional[float]:
    """USD this one ledger delta moved into (+) or out of (-) our equity.
    None when the type is unknown (the caller must not guess)."""
    t = delta.get("type")
    if t in IGNORED or t == "accountClassTransfer":
        return 0.0
    if t in _IN:
        return _f(delta.get(_IN[t]))
    if t == "withdraw":
        return -(_f(delta.get("usdc")) + _f(delta.get("fee")))
    if t == "vaultDeposit":
        return -_f(delta.get("usdc"))
    if t == "vaultCreate":
        return -(_f(delta.get("usdc")) + _f(delta.get("fee")))
    if t == "vaultWithdraw":
        net = delta.get("netWithdrawnUsd")
        return _f(net if net is not None else delta.get("usdc"))
    if t in _PEER:
        src = str(delta.get("user") or "").lower()
        dst = str(delta.get("destination") or "").lower()
        if t in ("send", "spotTransfer"):
            usdc = str(delta.get("token") or "") == "USDC"
            amount = _f(delta.get("amount")) if usdc else 0.0
            fee_in_usdc = str(delta.get("feeToken") or "") in ("", "USDC")
            fee = _f(delta.get("fee")) if fee_in_usdc else 0.0
        else:
            amount = _f(delta.get("usdc"))
            fee = _f(delta.get("fee"))
        if src == our and dst == our:
            return -fee
        if dst == our:
            return amount
        if src == our:
            return -(amount + fee)
        return 0.0   # not ours (should not appear in our own ledger)
    return None


def net_transfers(rows: List[Dict[str, Any]], our: str, start_ms: int,
                  read_ms: int) -> Tuple[float, Optional[str]]:
    """(net USD in, problem). Rows before start_ms are already in the anchor's
    equity and skipped. problem is None when the sum can be trusted."""
    our = our.lower()
    net = 0.0
    for row in rows:
        try:
            t = int(row["time"])
            delta = row["delta"]
            if t < start_ms:
                continue
            usd = delta_usd(delta, our)
        except (KeyError, TypeError, ValueError):
            return net, "unreadable ledger row"
        if usd is None:
            return net, f"unknown ledger type {delta.get('type')!r}"
        if usd and t > read_ms - AMBIGUITY_MS:
            return net, "transfer settling (inside the account read window)"
        net += usd
    return net, None
