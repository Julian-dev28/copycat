"""Board query (spec section 5): the api's query dict -> one parameterised
SQL statement on scout_rows for the served refresh_id.

Input: the plain dict the api sends (keys: window, preset, coin, min_av,
max_av, min_pnl, max_pnl, style, min_fit, max_fit, max_dd, min_trips,
active_within_h, hide_flagged, q, sort, order, limit, offset). Unset = None.
Enums as their string values. Values are re-validated here (the CLI and
tests call this without the api), and a bad value raises ScoutQueryError,
never a silent "no filter".

Sorting: NULLs always last, address as the final tie-break, so paging is
stable. `pnl`, `roi`, `volume` sort on the selected window's column.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from contracts.models import TradingStyle

from . import config as C

WINDOWS = {"1d", "7d", "30d", "all"}
SORTS = {
    "fit": "fit", "sim_return": "sim_return", "sim_dd": "sim_dd", "pnl": "pnl_{w}", "roi": "roi_{w}",
    "account_value": "account_value", "sharpe": "sharpe", "max_dd": "max_dd", "win_rate": "win_rate",
    "trips": "trips", "last_active": "last_fill_ms", "volume": "vlm_{w}",
}
STYLES = {s.value for s in TradingStyle}


class ScoutQueryError(ValueError):
    pass


@dataclass
class Query:
    window: str = "30d"
    preset: str = "all"
    coins: Tuple[str, ...] = ()
    styles: Tuple[str, ...] = ()
    min_av: Optional[float] = None
    max_av: Optional[float] = None
    min_pnl: Optional[float] = None
    max_pnl: Optional[float] = None
    min_fit: Optional[float] = None
    max_fit: Optional[float] = None
    max_dd: Optional[float] = None
    min_trips: Optional[int] = None
    active_within_h: Optional[float] = None
    hide_flagged: bool = False
    q: Optional[str] = None
    sort: str = "fit"
    order: str = "desc"
    limit: int = C.PAGE_LIMIT_DEFAULT
    offset: int = 0


def _val(v: Any) -> Any:
    return getattr(v, "value", v)     # enum -> its value


def _num(d: Dict[str, Any], k: str, cast=float) -> Any:
    v = d.get(k)
    if v is None or v == "":
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise ScoutQueryError(f"{k}: not a number: {v!r}") from None


def _list(v: Any) -> Tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        v = [x for x in v.split(",")]
    out: List[str] = []
    for x in v:
        x = str(_val(x)).strip()
        if x and x not in out:
            out.append(x)
    return tuple(out)


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def parse(d: Optional[Dict[str, Any]]) -> Query:
    d = dict(d or {})
    q = Query()
    q.window = str(_val(d.get("window")) or "30d")
    if q.window not in WINDOWS:
        raise ScoutQueryError(f"window: {q.window!r} not in {sorted(WINDOWS)}")
    q.preset = str(_val(d.get("preset")) or "all")
    if not (q.preset in ("all", "hip3") or (q.preset.startswith("coin:") and len(q.preset) > 5)):
        raise ScoutQueryError(f"preset: {q.preset!r} (all, hip3, coin:<COIN>)")
    q.coins = _list(d.get("coin"))
    q.styles = _list(d.get("style"))
    bad = [s for s in q.styles if s not in STYLES]
    if bad:
        raise ScoutQueryError(f"style: {bad} not in {sorted(STYLES)}")
    for k in ("min_av", "max_av", "min_pnl", "max_pnl", "min_fit", "max_fit", "max_dd", "active_within_h"):
        setattr(q, k, _num(d, k))
    q.min_trips = _num(d, "min_trips", int)
    for lo, hi in (("min_av", "max_av"), ("min_pnl", "max_pnl"), ("min_fit", "max_fit")):
        a, b = getattr(q, lo), getattr(q, hi)
        if a is not None and b is not None and a > b:
            raise ScoutQueryError(f"{lo} > {hi}")
    q.hide_flagged = _bool(d.get("hide_flagged"))
    qs = d.get("q")
    q.q = str(qs).strip().lower() or None if qs is not None else None
    q.sort = str(_val(d.get("sort")) or "fit")
    if q.sort not in SORTS:
        raise ScoutQueryError(f"sort: {q.sort!r} not in {sorted(SORTS)}")
    q.order = str(_val(d.get("order")) or "desc").lower()
    if q.order not in ("asc", "desc"):
        raise ScoutQueryError(f"order: {q.order!r}")
    lim = _num(d, "limit", int)
    q.limit = C.PAGE_LIMIT_DEFAULT if lim is None else lim
    if not 1 <= q.limit <= C.PAGE_LIMIT_MAX:
        raise ScoutQueryError(f"limit: {q.limit} not in 1..{C.PAGE_LIMIT_MAX}")
    off = _num(d, "offset", int)
    q.offset = 0 if off is None else off
    if q.offset < 0:
        raise ScoutQueryError("offset < 0")
    return q


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def where(q: Query, refresh_id: str, now_ms: Optional[int] = None) -> Tuple[str, List[Any]]:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    w = q.window
    clauses = ["refresh_id = ?"]
    args: List[Any] = [refresh_id]

    def rng(col: str, lo: Optional[float], hi: Optional[float]) -> None:
        if lo is not None:
            clauses.append(f"{col} >= ?")
            args.append(lo)
        if hi is not None:
            clauses.append(f"{col} <= ?")
            args.append(hi)

    rng("account_value", q.min_av, q.max_av)
    rng(f"pnl_{w}", q.min_pnl, q.max_pnl)
    rng("fit", q.min_fit, q.max_fit)
    if q.max_dd is not None:
        clauses.append("max_dd <= ?")
        args.append(q.max_dd)
    if q.min_trips is not None:
        clauses.append("trips >= ?")
        args.append(q.min_trips)
    if q.active_within_h is not None:
        clauses.append("last_fill_ms >= ?")
        args.append(now_ms - int(q.active_within_h * C.HOUR_MS))
    if q.styles:
        clauses.append(f"style IN ({','.join('?' * len(q.styles))})")
        args.extend(q.styles)
    coins: Sequence[str] = list(q.coins)
    if q.preset == "hip3":
        clauses.append("coins_csv LIKE ?")       # any HIP-3 (dex:COIN) market in the top 5
        args.append("%:%")
    elif q.preset.startswith("coin:"):
        clauses.append("top_coin = ?")
        args.append(q.preset[5:])
    for c in coins:
        clauses.append("coins_csv LIKE ? ESCAPE '\\'")
        args.append(f"%,{_like_escape(c)},%")
    if q.hide_flagged:
        clauses.append("flagged = 0")
    if q.q:
        clauses.append("(address LIKE ? ESCAPE '\\' OR display_name LIKE ? ESCAPE '\\')")
        args.extend([f"{_like_escape(q.q)}%", f"%{_like_escape(q.q)}%"])
    return " AND ".join(clauses), args


def order_by(q: Query) -> str:
    col = SORTS[q.sort].format(w=q.window)
    return f"({col} IS NULL) ASC, {col} {q.order.upper()}, address ASC"
