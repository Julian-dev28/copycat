"""Fakes for the /api/accounts tests: Hyperliquid behind vault.hlops, and the
hl/engine/discovery reads behind AccountsBackend. The vault itself runs for real
in a temp data dir."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from api.accounts_backend import AccountsBackend

from contracts.models import EngineStatus


class FakeHL:
    def __init__(self) -> None:
        self.agents: Dict[str, List[Dict[str, Any]]] = {}
        self.posts: List[Dict[str, Any]] = []
        self.unfunded: set = set()

    def extra_agents(self, user: str):
        return [dict(a) for a in self.agents.get(user.lower(), [])]

    def post_signed_action(self, action, nonce, signature):
        from hl import accounts as acc
        self.posts.append({"action": dict(action), "nonce": nonce})
        if action["type"] == "approveAgent":
            main = acc.recover_typed_signer(acc.approve_agent_typed_data(action), signature).lower()
            if main in self.unfunded:
                return {"status": "err", "response": f"User or API Wallet {main} does not exist."}
            self.approve(main, action["agentAddress"], action["agentName"])
        return {"status": "ok", "response": {"type": "default"}}

    def approve(self, main: str, agent: str, name: str = "bot") -> None:
        rows = [a for a in self.agents.get(main.lower(), []) if a["name"] != name]
        rows.append({"name": name, "address": agent.lower(),
                     "validUntil": int(time.time() * 1000) + 90 * 24 * 3600 * 1000})
        self.agents[main.lower()] = rows


class FakeBackend(AccountsBackend):
    """Real vault; canned hl / engine / discovery reads."""

    def __init__(self) -> None:
        self.state: Optional[Dict[str, Any]] = {
            "equity_perp_usd": 1000.0, "spot_usdc": 50.0, "abstraction": "default",
            "available": {"": 400.0, "xyz": 100.0},
            "raw_positions": {
                "BTC": {"szi": "0.01", "positionValue": "900.0", "unrealizedPnl": "12.5", "marginUsed": "90.0"},
                "xyz:TSLA": {"szi": "-1", "positionValue": "300.0", "unrealizedPnl": "-2.5", "marginUsed": "30.0"},
            }}
        self.extras_v = {"spot_other_usd": 25.0, "staked_hype_usd": 100.0}
        self.portfolio_v = [["allTime", {"accountValueHistory": [[1, "900"], [2, "1000"]],
                                         "pnlHistory": [[1, "0"], [2, "150.5"]], "vlm": "12345.6"}],
                            ["day", {"accountValueHistory": [], "pnlHistory": [], "vlm": "0"}]]
        self.engine: Dict[str, EngineStatus] = {}
        self.metrics_v: Optional[Dict[str, Any]] = None
        self.fills_v = [{"time_ms": 5, "coin": "BTC", "px": 100.0, "sz": 2.0, "side": "B", "dir": "Open Long",
                         "start_position": 0.0, "closed_pnl": 0.0, "fee": 0.1}]
        self.orders_v = [{"order": {"coin": "BTC", "side": "B", "limitPx": "100", "sz": "0", "oid": 1,
                                    "timestamp": 4}, "status": "filled", "statusTimestamp": 5}]
        self.ledger_v = [{"time": 7, "hash": "0xh", "delta": {"type": "deposit", "usdc": "500.0"}}]
        self.spot_v = [{"coin": "USDC", "total": "50.0", "hold": "0.0"}, {"coin": "HYPE", "total": "2", "hold": "0"}]

    def account_state(self, address):
        return self.state

    def extras(self, address):
        return self.extras_v

    def portfolio(self, address):
        return self.portfolio_v

    def fills(self, address):
        return self.fills_v

    def historical_orders(self, address):
        return self.orders_v

    def ledger_updates(self, address):
        return self.ledger_v

    def spot_balances(self, address):
        return self.spot_v

    def engine_status(self, address):
        return self.engine.get(address)

    def metrics(self, address):
        return self.metrics_v
