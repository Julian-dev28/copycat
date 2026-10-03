"""Candidate pull from the HL leaderboard (contracts.venue.Venue.leaderboard).

ASSUMED ROW SHAPE (services/hl returns "raw HL leaderboard rows" per the
Venue contract, undefined further there). We assume Hyperliquid's public
stats-data leaderboard payload shape, the one documented/observed in the
wild:

    {
        "ethAddress": "0x...",
        "accountValue": "12345.67",
        "displayName": "whale" | None,
        "windowPerformances": [
            ["day",   {"pnl": "1.2",  "roi": "0.01", "vlm": "500.0"}],
            ["week",  {...}],
            ["month", {"pnl": "...", "roi": "...", "vlm": "..."}],
            ["allTime", {"pnl": "...", "roi": "...", "vlm": "..."}],
        ],
        # some dumps mark vault/subaccount rows explicitly; field name varies
        # by source, so we check a few.
        "isVault": false,
    }

All parsing goes through `_parse_row` below. If services/hl's real payload
differs, this is the only function that needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from contracts.venue import Venue

WINDOW_30D = "month"     # HL's own bucket name for ~30d; not strictly trailing-30d (documented bias)
WINDOW_ALL = "allTime"


@dataclass
class Candidate:
    address: str
    display_name: Optional[str]
    account_value_usd: float
    pnl_30d_usd: float
    roi_30d_pct: float
    pnl_all_time_usd: float
    volume_30d_usd: float
    is_vault: bool
    flags: List[str] = field(default_factory=list)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_row(row: Dict[str, Any]) -> Optional[Candidate]:
    address = row.get("ethAddress") or row.get("address") or row.get("user")
    if not address:
        return None
    windows: Dict[str, Dict[str, Any]] = {}
    wp = row.get("windowPerformances")
    if isinstance(wp, list):
        for pair in wp:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                windows[pair[0]] = pair[1] or {}
    elif isinstance(wp, dict):
        windows = wp

    month = windows.get(WINDOW_30D, {})
    all_time = windows.get(WINDOW_ALL, {})

    is_vault = bool(row.get("isVault") or row.get("is_vault") or row.get("vaultAddress"))

    return Candidate(
        address=str(address).strip().lower(),
        display_name=row.get("displayName") or row.get("display_name"),
        account_value_usd=_f(row.get("accountValue")),
        pnl_30d_usd=_f(month.get("pnl")),
        roi_30d_pct=_f(month.get("roi")) * 100.0,
        pnl_all_time_usd=_f(all_time.get("pnl")),
        volume_30d_usd=_f(month.get("vlm")),
        is_vault=is_vault,
    )


def pull_candidates(
    venue: Venue,
    min_account_value_usd: float,
    min_volume_30d_usd: float,
    top_n: int = 50,
) -> List[Candidate]:
    """Pull the leaderboard, filter, rank by 30d PnL, return the top_n.

    Filters (all required):
      - account_value_usd >= min_account_value_usd
      - volume_30d_usd >= min_volume_30d_usd
      - pnl_30d_usd > 0 AND pnl_all_time_usd > 0

    Vaults are kept but flagged "vault" (vault PnL isn't attributable to one
    trader's decisions in the same way; the caller may still want to see them
    ranked, so we don't drop them). HFT flagging (opens/day > 100) needs fill
    history and happens later, once fills are cached (see discovery.stats).
    """
    raw = venue.leaderboard()
    if not raw:
        return []

    candidates: List[Candidate] = []
    seen: set[str] = set()
    for row in raw:
        c = _parse_row(row)
        if c is None or c.address in seen:
            continue
        seen.add(c.address)
        if c.account_value_usd < min_account_value_usd:
            continue
        if c.volume_30d_usd < min_volume_30d_usd:
            continue
        if not (c.pnl_30d_usd > 0 and c.pnl_all_time_usd > 0):
            continue
        if c.is_vault:
            c.flags.append("vault")
        candidates.append(c)

    candidates.sort(key=lambda c: c.pnl_30d_usd, reverse=True)
    return candidates[:top_n]
