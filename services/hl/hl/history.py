"""Read-only account history for the Account page (api GET /api/accounts/{id}/history).

Each function returns HL's raw rows, or None on a failed read (never [] for a
failure: an empty list means "nothing happened"). The api maps rows to display
shapes. Weights: historicalOrders 20 + 1 per 20 rows, userNonFundingLedgerUpdates
20, spotClearinghouseState 2 (hl.rate_limit).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .http import http_post


def historical_orders(user: str) -> Optional[List[Dict[str, Any]]]:
    """Most recent orders (HL returns at most 2000), newest first."""
    raw = http_post("/info", {"type": "historicalOrders", "user": user}, item_count=2000)
    return raw if isinstance(raw, list) else None


def ledger_updates(user: str, start_ms: int, end_ms: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
    """Deposits, withdrawals, usdSend, class transfers, ... (non-funding ledger)."""
    payload: Dict[str, Any] = {"type": "userNonFundingLedgerUpdates", "user": user, "startTime": int(start_ms)}
    if end_ms is not None:
        payload["endTime"] = int(end_ms)
    raw = http_post("/info", payload)
    return raw if isinstance(raw, list) else None


def spot_balances(user: str) -> Optional[List[Dict[str, Any]]]:
    """[{coin, total, hold, entryNtl, token}] from spotClearinghouseState."""
    raw = http_post("/info", {"type": "spotClearinghouseState", "user": user})
    if not isinstance(raw, dict) or not isinstance(raw.get("balances"), list):
        return None
    return raw["balances"]
