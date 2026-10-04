"""Live eval (READ ONLY): `make eval` / pytest -m live. Hits HL /info extraAgents."""
from __future__ import annotations

import time

import pytest
from vault import agents

from contracts.models import AgentStatus

USER = "0x2c2e4efF574B3Fd9879AdeF9c5CAC6fD7C916985"


@pytest.mark.live
def test_extra_agents_lists_hypememe_with_valid_until():
    rows = agents.lookup(USER, force=True)
    assert rows is not None, "extraAgents read failed"
    hit = next((r for r in rows if r["name"] == "hypememe"), None)
    assert hit is not None, rows
    assert hit["address"].startswith("0x") and len(hit["address"]) == 42
    now = int(time.time() * 1000)
    assert isinstance(hit["validUntil"], int) and hit["validUntil"] > 1_600_000_000_000
    status, vu = agents.classify(hit["address"], rows, None, now)
    assert status in (AgentStatus.active, AgentStatus.expiring, AgentStatus.expired)
    assert vu == hit["validUntil"]
    print(f"hypememe agent {hit['address']} validUntil {hit['validUntil']} -> {status.value}")
