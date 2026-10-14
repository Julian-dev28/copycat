"""account_history.py's pure row shapers (GET /api/accounts/{id}/history).
No FastAPI, no I/O: these take raw-ish HL rows and return display shapes."""
from __future__ import annotations

import pytest
from api import account_history as H


def test_fills_computes_liquidation_from_dir_not_hl_bool():
    """Trade history checklist: a liquidation is its own event type. The
    account's own fills use the same dir-prefix check as
    discovery.scout.metrics.real_liquidations, never HL's raw `liquidation`
    bool (which also fires on a counterparty absorbing someone ELSE's
    liquidation)."""
    rows = [
        {"time_ms": 3, "coin": "BTC", "side": "A", "dir": "Close Long", "px": 100, "sz": 1, "closed_pnl": 5, "fee": 0.1},
        {"time_ms": 2, "coin": "ETH", "side": "A", "dir": "Liquidated Isolated Long", "px": 50, "sz": 2, "closed_pnl": -40, "fee": 0},
        {"time_ms": 1, "coin": "SOL", "side": "A", "dir": "Open Long", "px": 10, "sz": 1, "liquidation": True},  # counterparty fill
    ]
    out = H.fills(rows)
    assert [r["time_ms"] for r in out] == [3, 2, 1]   # newest first
    assert [r["liquidation"] for r in out] == [False, True, False]


def test_fills_drops_non_perp_sides_and_defaults_missing_numbers():
    rows = [
        {"time_ms": 1, "coin": "BTC", "side": "B", "px": "100", "sz": "2"},   # strings coerce
        {"time_ms": 2, "coin": "SPOT", "side": "X", "px": 1, "sz": 1},        # not B/A: dropped
    ]
    out = H.fills(rows)
    assert len(out) == 1
    assert out[0] == {
        "time_ms": 1, "coin": "BTC", "side": "B", "dir": "", "px": 100.0, "sz": 2.0,
        "notional_usd": 200.0, "closed_pnl_usd": 0.0, "fee_usd": 0.0, "liquidation": False,
    }


def test_orders_flattens_and_sorts_newest_status_first():
    rows = [
        {"order": {"coin": "BTC", "oid": 1}, "status": "open", "statusTimestamp": 100},
        {"order": {"coin": "ETH", "oid": 2}, "status": "filled", "statusTimestamp": 300},
        {"status": "filled"},   # no "order": dropped
    ]
    out = H.orders(rows)
    assert [o["oid"] for o in out] == [2, 1]
    assert out[0]["status"] == "filled" and out[0]["coin"] == "ETH"


def test_transfers_normalizes_time_and_sorts_newest_first():
    rows = [{"time": 5, "hash": "a"}, {"time": 10, "hash": "b"}, "not a dict"]
    out = H.transfers(rows)
    assert [r["time_ms"] for r in out] == [10, 5]


def test_balances_adds_a_perps_row_and_values_usdc_at_par():
    out = H.balances(
        [{"coin": "USDC", "total": "500.5", "hold": "10"}, {"coin": "PURR", "total": "100"}, {"coin": None, "total": 1}],
        {"equity_perp_usd": "1234.5"},
    )
    assert out[0] == {"coin": "USDC (perps)", "total": 1234.5, "hold": 0.0, "usd_value": 1234.5}
    usdc = next(r for r in out if r["coin"] == "USDC")
    assert usdc["usd_value"] == pytest.approx(500.5)
    purr = next(r for r in out if r["coin"] == "PURR")
    assert purr["usd_value"] is None   # not priced here: the web prices it, or shows "--"


def test_balances_without_perp_state_has_no_perps_row():
    out = H.balances([], None)
    assert out == []
