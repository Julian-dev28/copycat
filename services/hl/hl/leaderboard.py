"""Pure parsing for the stats-data leaderboard rows `HlVenue.leaderboard()`
returns. No network, no state: discovery's Scout pipeline calls
`parse_rows(venue.leaderboard())` and gets typed floats instead of HL's
string-encoded numbers.

Raw row (curled 2026-10-02, Mainnet):

    {"ethAddress": "0x85ec...2052",
     "accountValue": "62330451.1721990108",
     "windowPerformances": [
        ["day",     {"pnl": "310963.157278", "roi": "0.0055071207", "vlm": "1450003736.83"}],
        ["week",    {...}], ["month", {...}], ["allTime", {...}]],
     "prize": 0,
     "displayName": null}

Parsed row:

    {"address": "0x85ec...2052", "display_name": None, "account_value": 62330451.17,
     "day":     {"pnl": 310963.16, "roi": 0.0055, "vlm": 1450003736.83},
     "week": {...}, "month": {...}, "allTime": {...}}

A row missing any of the four windows, or with any number that does not
parse to a finite float, is DROPPED (logged in aggregate), never
zero-filled: a zero-filled window would look like a real flat trader to a
scorer, and the "a failed read must never look flat" rule from
contracts/venue.py applies here too.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)

WINDOWS = ("day", "week", "month", "allTime")


class WindowPerf(TypedDict):
    pnl: float   # USD
    roi: float   # fraction (0.05 = 5%), as HL reports it
    vlm: float   # USD notional traded in the window


class LeaderboardRow(TypedDict):
    address: str               # lowercased 0x address
    display_name: Optional[str]
    account_value: float       # USD
    day: WindowPerf
    week: WindowPerf
    month: WindowPerf
    allTime: WindowPerf


def _num(v: Any) -> float:
    """HL string (or number) -> finite float. Raises ValueError otherwise.
    bool is rejected: it is an int subclass and never a real HL value."""
    if isinstance(v, bool) or v is None:
        raise ValueError(f"not a number: {v!r}")
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"non-finite: {v!r}")
    return f


def parse_row(raw: Any) -> Optional[LeaderboardRow]:
    """One raw stats-data row -> LeaderboardRow, or None if it is malformed."""
    try:
        if not isinstance(raw, dict):
            return None
        addr = raw.get("ethAddress")
        if not isinstance(addr, str) or not addr.startswith("0x") or len(addr) != 42:
            return None
        perfs = raw.get("windowPerformances")
        if not isinstance(perfs, list):
            return None
        by_label: Dict[str, Any] = {}
        for pair in perfs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str):
                by_label[pair[0]] = pair[1]
        name = raw.get("displayName")
        out: Dict[str, Any] = {
            "address": addr.lower(),
            "display_name": name if isinstance(name, str) and name else None,
            "account_value": _num(raw.get("accountValue")),
        }
        for w in WINDOWS:
            perf = by_label.get(w)
            if not isinstance(perf, dict):
                return None
            out[w] = {"pnl": _num(perf.get("pnl")), "roi": _num(perf.get("roi")),
                      "vlm": _num(perf.get("vlm"))}
        return out  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def parse_rows(raw: Any) -> List[LeaderboardRow]:
    """`HlVenue.leaderboard()` output (a list of raw rows) -> typed rows.

    Also accepts the whole response body `{"leaderboardRows": [...]}`.
    Malformed rows are dropped (count logged once per call). `None` or any
    other non-list input -> `[]`; callers that must tell "leaderboard read
    failed" from "empty leaderboard" check `leaderboard()` for None first.
    """
    if isinstance(raw, dict):
        raw = raw.get("leaderboardRows")
    if not isinstance(raw, list):
        return []
    out: List[LeaderboardRow] = []
    dropped = 0
    for r in raw:
        p = parse_row(r)
        if p is None:
            dropped += 1
        else:
            out.append(p)
    if dropped:
        logger.warning(f"[hl.leaderboard] dropped {dropped}/{len(raw)} malformed leaderboard rows")
    return out
