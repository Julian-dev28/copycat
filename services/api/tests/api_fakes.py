"""Fakes for engine.public / discovery.public, satisfying the EngineClient
/ DiscoveryClient Protocols. Tests inject these via
app.dependency_overrides so no test ever imports the real `engine` or
`discovery` packages (which may not exist yet / are built in parallel).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from contracts.models import DiscoveryRun, EngineEvent, EngineStatus, Settings
from api.discovery_client import DiscoveryUnavailable
from api.engine_client import EngineUnavailable


class FakeEngineClient:
    def __init__(self) -> None:
        self._status = EngineStatus(running=True, enabled=False, dry_run=True)
        self.event_log: List[EngineEvent] = []

    def status(self) -> EngineStatus:
        return self._status

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]:
        evs = self.event_log
        if since_ms is not None:
            evs = [e for e in evs if e.ts_ms >= since_ms]
        return list(reversed(evs))[:limit]


class UnavailableEngineClient:
    """Simulates services/engine not being importable yet."""

    def status(self) -> EngineStatus:
        raise EngineUnavailable("services/engine isn't importable yet: boom")

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]:
        raise EngineUnavailable("services/engine isn't importable yet: boom")


class FakeDiscoveryClient:
    def __init__(self) -> None:
        self.runs: Dict[str, DiscoveryRun] = {}
        self.calls: List[tuple] = []
        self._latest: Optional[DiscoveryRun] = None
        self._next_id = 0

    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str:
        self.calls.append((settings, sim_equity_usd, top_n))
        self._next_id += 1
        run_id = f"run-{self._next_id}"
        run = DiscoveryRun(
            run_id=run_id,
            started_ms=0,
            status="running",
            sim_equity_usd=sim_equity_usd,
            sim_settings=settings,
            candidates=0,
            scored=0,
        )
        self.runs[run_id] = run
        self._latest = run
        return run_id

    def get_run(self, run_id: str) -> DiscoveryRun:
        if run_id not in self.runs:
            raise KeyError(run_id)
        return self.runs[run_id]

    def latest(self) -> Optional[DiscoveryRun]:
        return self._latest


class UnavailableDiscoveryClient:
    """Simulates services/discovery not being importable yet."""

    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str:
        raise DiscoveryUnavailable("services/discovery isn't importable yet: boom")

    def get_run(self, run_id: str) -> DiscoveryRun:
        raise DiscoveryUnavailable("services/discovery isn't importable yet: boom")

    def latest(self) -> Optional[DiscoveryRun]:
        raise DiscoveryUnavailable("services/discovery isn't importable yet: boom")
