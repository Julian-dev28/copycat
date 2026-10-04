"""Vault gate fixtures: a temp COPYCAT_DATA_DIR and a fake Hyperliquid behind
vault.hlops (post_signed_action + extra_agents). Signing runs for real (it is
pure); nothing touches the network."""
from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest
from vault import agents, approval, hlops

DAY_MS = 24 * 3600 * 1000


class FakeHL:
    def __init__(self) -> None:
        self.agents: Dict[str, List[Dict[str, Any]]] = {}
        self.posts: List[Dict[str, Any]] = []
        self.unfunded: set = set()
        self.reject: str = ""
        self.read_fails = False
        self.listing_delay = 0          # extraAgents misses the new agent this many times
        self.valid_ms = 180 * DAY_MS

    def extra_agents(self, user: str):
        if self.read_fails:
            return None
        if self.listing_delay > 0:
            self.listing_delay -= 1
            return []
        return [dict(a) for a in self.agents.get(user.lower(), [])]

    def post_signed_action(self, action, nonce, signature):
        self.posts.append({"action": dict(action), "nonce": nonce, "signature": dict(signature)})
        if self.reject:
            return {"status": "err", "response": self.reject}
        if action["type"] == "approveAgent":
            main = self._signer(action, signature)
            if main in self.unfunded:
                return {"status": "err", "response": f"User or API Wallet {main} does not exist."}
            rows = [a for a in self.agents.get(main, []) if a["name"] != action["agentName"]]
            rows.append({"name": action["agentName"], "address": action["agentAddress"].lower(),
                         "validUntil": int(time.time() * 1000) + self.valid_ms})
            self.agents[main] = rows
        return {"status": "ok", "response": {"type": "default"}}

    @staticmethod
    def _signer(action, signature) -> str:
        from hl import accounts as acc
        return acc.recover_typed_signer(acc.approve_agent_typed_data(action), signature).lower()

    def approve(self, main: str, agent: str, name: str = "bot", valid_until: int = 0) -> None:
        self.agents.setdefault(main.lower(), []).append(
            {"name": name, "address": agent.lower(),
             "validUntil": valid_until or int(time.time() * 1000) + self.valid_ms})


@pytest.fixture(autouse=True)
def vault_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COPYCAT_NETWORK", "mainnet")
    monkeypatch.setattr(approval, "_sleep", lambda s: None)
    agents.invalidate()
    yield tmp_path / "data"
    agents.invalidate()


@pytest.fixture
def fake_hl(monkeypatch) -> FakeHL:
    hl = FakeHL()
    monkeypatch.setattr(hlops, "extra_agents", hl.extra_agents)
    monkeypatch.setattr(hlops, "post_signed_action", hl.post_signed_action)
    return hl
