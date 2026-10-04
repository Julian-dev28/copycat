"""Row shapes for GET /api/accounts/{id}/history?kind=fills|orders|transfers|balances.

  fills      LeaderFillView fields: time_ms, coin, side B|A, dir, px, sz, notional_usd,
             closed_pnl_usd, fee_usd (last 30 days, newest first)
  orders     HL historicalOrders flattened: the order's own fields (coin, side, limitPx,
             sz, origSz, oid, cloid, orderType, reduceOnly, timestamp, ...) + status,
             status_ms (newest first, at most 2000)
  transfers  HL userNonFundingLedgerUpdates rows {time_ms, hash, delta{type, usdc, ...}}
             (last 365 days, newest first)
  balances   spot balances {coin, total, hold, usd_value?} plus one row for perps USDC
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

HISTORY_KINDS = ("fills", "orders", "transfers", "balances")


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fills(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = [{"time_ms": int(r["time_ms"]), "coin": r["coin"], "side": r["side"], "dir": r.get("dir") or "",
            "px": _f(r["px"]), "sz": _f(r["sz"]), "notional_usd": round(_f(r["px"]) * _f(r["sz"]), 2),
            "closed_pnl_usd": _f(r.get("closed_pnl")), "fee_usd": _f(r.get("fee"))}
           for r in rows if r.get("side") in ("B", "A")]
    return sorted(out, key=lambda r: -r["time_ms"])


def orders(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        order = r.get("order") if isinstance(r.get("order"), dict) else None
        if order is None:
            continue
        out.append({**order, "status": r.get("status"), "status_ms": r.get("statusTimestamp")})
    return sorted(out, key=lambda r: -int(r.get("status_ms") or r.get("timestamp") or 0))


def transfers(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = [{**r, "time_ms": int(r.get("time") or 0)} for r in rows if isinstance(r, dict)]
    return sorted(out, key=lambda r: -r["time_ms"])


def balances(spot: List[Dict[str, Any]], state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if state is not None:
        out.append({"coin": "USDC (perps)", "total": round(_f(state.get("equity_perp_usd")), 2), "hold": 0.0,
                    "usd_value": round(_f(state.get("equity_perp_usd")), 2)})
    for b in spot:
        coin = b.get("coin")
        if not coin:
            continue
        total = _f(b.get("total"))
        out.append({"coin": coin, "total": total, "hold": _f(b.get("hold")),
                    "usd_value": round(total, 2) if coin == "USDC" else None})
    return out
