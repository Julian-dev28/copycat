"""Read-only account history for the Account page (api GET /api/accounts/{id}/history).

Each function returns HL's raw rows, or None on a failed read (never [] for a
failure: an empty list means "nothing happened"). The api maps rows to display
shapes. Weights: historicalOrders 20 + 1 per 20 rows, userNonFundingLedgerUpdates
20 + 1 per 20 rows, spotClearinghouseState 2 (hl.rate_limit).

`ledger_since` is the engine's read (day PnL net of transfers): every page from
a start time, never a silently truncated list.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .http import http_post


def historical_orders(user: str) -> Optional[List[Dict[str, Any]]]:
    """Most recent orders (HL returns at most 2000), newest first."""
    raw = http_post("/info", {"type": "historicalOrders", "user": user})
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


# HL answers userNonFundingLedgerUpdates with at most this many rows per call,
# oldest first from startTime (measured 2026-10-11 on the HLP vault: exactly 2000).
LEDGER_PAGE_ROWS = 2000
LEDGER_MAX_PAGES = 5


def ledger_since(user: str, start_ms: int, max_pages: int = LEDGER_MAX_PAGES,
                 page_rows: int = LEDGER_PAGE_ROWS) -> Optional[List[Dict[str, Any]]]:
    """Every non-funding ledger row with time >= start_ms, oldest first.

    A full page (page_rows rows) means there may be more: the next page starts
    at the last row's time (inclusive, so rows sharing that millisecond are not
    lost) and rows already seen are dropped by (hash, time, delta). None when any
    page fails, a row is malformed, or the rows do not fit in max_pages pages:
    a caller netting transfers must never sum a partial list.
    Weight per page: 20 + 1 per 20 rows.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    cursor = int(start_ms)
    for _ in range(max_pages):
        page = ledger_updates(user, cursor)
        if page is None:
            return None
        new = 0
        for row in page:
            if not isinstance(row, dict) or not isinstance(row.get("delta"), dict):
                return None
            try:
                t = int(row.get("time"))
            except (TypeError, ValueError):
                return None
            key = (row.get("hash"), t, repr(sorted(row["delta"].items())))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            new += 1
        if len(page) < page_rows:
            out.sort(key=lambda r: int(r["time"]))
            return out
        last = max(int(r["time"]) for r in page)
        if new == 0 or last < cursor:
            return None   # a full page of rows we already have: cannot make progress
        cursor = last
    return None
