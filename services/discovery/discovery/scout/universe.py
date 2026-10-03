"""Stage A: the Scout universe from the stats-data leaderboard (spec 7.2).

One GET (no /info weight), parsed by `hl.leaderboard.parse_rows` (rows
missing a window are dropped there, never zero-filled). Filters:
account value >= $10k, 30d volume >= $50k, allTime PnL > 0 OR 30d PnL > 0,
vaults out unless COPYCAT_SCOUT_INCLUDE_VAULTS=1; keep the top 300 by 30d
PnL. Wallets in the user's book are always kept (source 'book'), whatever
the filters say, so the book is always on the board.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from contracts.venue import Venue

from . import config as C

logger = logging.getLogger(__name__)

_WIN = {"day": "1d", "week": "7d", "month": "30d", "allTime": "all"}


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _parse_rows_local(raw: Any) -> List[Dict[str, Any]]:
    """Same output shape as hl.leaderboard.parse_rows, used only when hl is
    not importable (discovery's offline tests)."""
    rows = raw.get("leaderboardRows") if isinstance(raw, dict) else raw
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("ethAddress"):
            continue
        wp = r.get("windowPerformances")
        wins = dict(p for p in wp if isinstance(p, (list, tuple)) and len(p) == 2) if isinstance(wp, list) else (wp or {})
        row: Dict[str, Any] = {"address": str(r["ethAddress"]).strip().lower(),
                               "display_name": r.get("displayName"), "account_value": _num(r.get("accountValue"))}
        ok = row["account_value"] is not None
        for w in _WIN:
            d = wins.get(w) or {}
            vals = {k: _num(d.get(k)) for k in ("pnl", "roi", "vlm")}
            ok = ok and all(v is not None for v in vals.values())
            row[w] = vals
        if ok:
            row["is_vault"] = bool(r.get("isVault") or r.get("vaultAddress"))
            out.append(row)
    return out


def parse_rows(raw: Any) -> List[Dict[str, Any]]:
    try:
        from hl.leaderboard import parse_rows as hl_parse
    except ImportError:
        return _parse_rows_local(raw)
    rows = hl_parse(raw)
    # hl's parser has no vault field; keep ours when the raw row carries one
    flags = {}
    for r in (raw.get("leaderboardRows") if isinstance(raw, dict) else raw) or []:
        if isinstance(r, dict) and (r.get("isVault") or r.get("vaultAddress")) and r.get("ethAddress"):
            flags[str(r["ethAddress"]).lower()] = True
    for r in rows:
        r["is_vault"] = flags.get(r["address"], bool(r.get("is_vault")))
    return rows


def to_universe_row(r: Dict[str, Any], source: str, now_ms: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"address": r["address"], "display_name": r.get("display_name"),
                           "account_value": float(r["account_value"]), "is_vault": int(bool(r.get("is_vault"))),
                           "source": source, "seen_ms": now_ms}
    for w, suf in _WIN.items():
        d = r.get(w) or {}
        out[f"pnl_{suf}"] = float(d.get("pnl") or 0.0)
        out[f"roi_{suf}"] = float(d.get("roi") or 0.0) * 100.0      # fraction -> percent
        out[f"vlm_{suf}"] = float(d.get("vlm") or 0.0)
    return out


def select(rows: Sequence[Dict[str, Any]], now_ms: int, book: Iterable[str] = (),
           size: int = C.UNIVERSE_SIZE, include_vaults: bool = C.INCLUDE_VAULTS) -> List[Dict[str, Any]]:
    book_set = {a.lower() for a in book}
    keep: List[Dict[str, Any]] = []
    in_book: Dict[str, Dict[str, Any]] = {}
    seen = set()
    for r in rows:
        a = r["address"]
        if a in seen:
            continue
        seen.add(a)
        if a in book_set:
            in_book[a] = r
        if r["account_value"] < C.UNIVERSE_MIN_ACCOUNT_VALUE:
            continue
        if r["month"]["vlm"] < C.UNIVERSE_MIN_VLM_30D:
            continue
        if not (r["allTime"]["pnl"] > 0 or r["month"]["pnl"] > 0):
            continue
        if r.get("is_vault") and not include_vaults:
            continue
        keep.append(r)
    keep.sort(key=lambda r: (-r["month"]["pnl"], r["address"]))
    out = [to_universe_row(r, "lb", now_ms) for r in keep[:size]]
    have = {r["address"] for r in out}
    for a, r in sorted(in_book.items()):
        if a not in have:
            out.append(to_universe_row(r, "book", now_ms))
    return out


def run_stage_a(venue: Venue, now_ms: int, book: Iterable[str] = ()) -> Optional[List[Dict[str, Any]]]:
    """None when the leaderboard read failed (the old universe keeps serving)."""
    raw = venue.leaderboard()
    if raw is None:
        logger.warning("scout stage A: leaderboard read failed, keeping the previous universe")
        return None
    rows = parse_rows(raw)
    if not rows:
        logger.warning("scout stage A: leaderboard parsed to 0 rows, keeping the previous universe")
        return None
    sel = select(rows, now_ms, book)
    logger.info("scout stage A: %d leaderboard rows -> %d in universe", len(rows), len(sel))
    return sel
