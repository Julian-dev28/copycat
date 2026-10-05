"""MCP gate tests never really wait: the 202 polling loop is capped to ~50 ms."""
import pytest


@pytest.fixture(autouse=True)
def _fast_waits(monkeypatch):
    import copycat_mcp.server as srv
    monkeypatch.setattr(srv, "WAIT_POLL_S", 0.01)
    monkeypatch.setattr(srv, "MAX_WAIT_S", 0.05)
