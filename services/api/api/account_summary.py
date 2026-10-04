"""Pure builders for GET /api/accounts/{id}/summary and .../history.

Balances and exposure come straight from hl reads (account_state, extras,
portfolio). Scout-style metrics (risk, trades, style, tiers, streak, daily pnl)
come from `discovery.scout.public.account_metrics(address)` when discovery
exposes it; until then those fields stay null (see services/api/README.md).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts.models import (
    AccountBalances,
    AccountSummary,
    CurvePoint,
    EngineStatus,
    PnlWindow,
    TradingAccount,
)

_WINDOWS = {"day": PnlWindow.day, "week": PnlWindow.week, "month": PnlWindow.month,
            "allTime": PnlWindow.all_time}
METRIC_FIELDS = ("longest_win_streak_days", "style", "avg_hold_h", "median_hold_h", "pnl_tier",
                 "size_tier", "risk_30d", "trades_30d", "daily_pnl")


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _points(raw: Any) -> List[CurvePoint]:
    out = []
    for p in raw or []:
        try:
            out.append(CurvePoint(t_ms=int(p[0]), value=float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def curves(portfolio: Optional[List[Any]]) -> Dict[str, Any]:
    pnl, value, vlm = {}, {}, None
    for item in portfolio or []:
        if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], dict)):
            continue
        name, body = item
        if name in _WINDOWS:
            pnl[_WINDOWS[name]] = _points(body.get("pnlHistory"))
            value[_WINDOWS[name]] = _points(body.get("accountValueHistory"))
            if name == "allTime":
                vlm = _f(body.get("vlm"))
    all_pnl = pnl.get(PnlWindow.all_time) or []
    return {"pnl_curve": pnl, "value_curve": value, "volume_usd": vlm,
            "all_time_pnl_usd": all_pnl[-1].value if all_pnl else None}


def copytrade_margin(status: Optional[EngineStatus], address: str) -> float:
    if status is None or (status.our_address or "").lower() != address.lower():
        return 0.0
    return round(sum(ls.margin_used_usd for ls in status.leaders), 2)


def build(account: TradingAccount, state: Dict[str, Any], extras: Optional[Dict[str, Any]],
          portfolio: Optional[List[Any]], engine_status: Optional[EngineStatus],
          metrics: Optional[Dict[str, Any]], now_ms: int) -> AccountSummary:
    perps = _f(state.get("equity_perp_usd"))
    spot_usdc = _f(state.get("spot_usdc"))
    ex = extras or {}
    spot = spot_usdc + _f(ex.get("spot_other_usd"))
    staked = _f(ex.get("staked_hype_usd"))
    unified = state.get("abstraction") in ("unifiedAccount", "portfolioMargin")
    avail = [_f(v) for v in (state.get("available") or {}).values()]
    withdrawable = max(avail, default=0.0) if unified else sum(avail)
    long_ntl = short_ntl = upnl = margin = 0.0
    for raw in (state.get("raw_positions") or {}).values():
        szi = _f(raw.get("szi"))
        ntl = abs(_f(raw.get("positionValue")))
        upnl += _f(raw.get("unrealizedPnl"))
        margin += _f(raw.get("marginUsed"))
        if szi > 0:
            long_ntl += ntl
        elif szi < 0:
            short_ntl += ntl
    # Unified accounts: spot holds the perp collateral, so do not count it twice.
    total = (spot + upnl if unified else perps + spot) + staked
    base = perps if perps > 0 else perps + spot_usdc
    fields: Dict[str, Any] = dict(
        account=account,
        balances=AccountBalances(perps_usd=round(perps, 2), spot_usd=round(spot, 2), staked_usd=round(staked, 2),
                                 copytrade_usd=copytrade_margin(engine_status, account.address),
                                 total_usd=round(total, 2), withdrawable_usd=round(withdrawable, 2)),
        unrealized_pnl_usd=round(upnl, 2),
        account_leverage=round((long_ntl + short_ntl) / base, 4) if base > 0 else 0.0,
        margin_usage_pct=round(margin / base * 100.0, 4) if base > 0 else 0.0,
        long_notional_usd=round(long_ntl, 2), short_notional_usd=round(short_ntl, 2),
        as_of_ms=now_ms, **curves(portfolio))
    for k in METRIC_FIELDS:
        if metrics and metrics.get(k) is not None:
            fields[k] = metrics[k]
    return AccountSummary.model_validate(fields)
