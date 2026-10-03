from __future__ import annotations

from discovery.tracing import compare_positions


def f(t, coin, sz, side, start):
    return {"time_ms": t, "coin": coin, "px": 1.0, "sz": sz, "side": side, "start_position": start,
            "fee": 0.0, "closed_pnl": 0.0}


def test_compare_positions_flags_mismatch_and_pre_window_holdings():
    fills = [f(0, "BTC", 1.0, "B", 0.0), f(1, "BTC", 0.5, "A", 1.0), f(2, "ETH", 2.0, "A", 0.0),
             f(3, "@151", 5.0, "B", 0.0)]
    live = {"BTC": {"szi": 0.5}, "ETH": {"szi": -1.0}, "SOL": {"szi": 3.0}}
    rows = {r["coin"]: r for r in compare_positions(fills, live)}
    assert rows["BTC"]["ok"] is True
    assert rows["ETH"]["ok"] is False                  # he traded ETH after our last fill, or we missed one
    assert rows["SOL"]["ok"] is None                   # held from before the window, never traded in it
    assert "@151" not in rows
