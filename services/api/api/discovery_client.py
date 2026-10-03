"""Adapter in front of services/discovery's public surface
(`discovery.public`). Same lazy-import reasoning as engine_client.py:
services/discovery is being built in parallel, so every call imports fresh
and routes never crash the process if it isn't there yet -- they get a 503.
"""
from __future__ import annotations

from typing import Optional, Protocol

from contracts.models import DiscoveryRun, Settings


class DiscoveryUnavailable(RuntimeError):
    """discovery.public isn't importable yet."""


class DiscoveryClient(Protocol):
    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str: ...

    def get_run(self, run_id: str) -> DiscoveryRun: ...

    def latest(self) -> Optional[DiscoveryRun]: ...


class RealDiscoveryClient:
    """Implements DiscoveryClient by calling discovery.public, imported lazily."""

    @staticmethod
    def _public():
        try:
            from discovery import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise DiscoveryUnavailable(
                f"services/discovery isn't importable yet: {e}"
            ) from e
        return public

    def start_run(self, settings: Settings, sim_equity_usd: float, top_n: int) -> str:
        return self._public().start_run(settings, sim_equity_usd, top_n)

    def get_run(self, run_id: str) -> DiscoveryRun:
        return self._public().get_run(run_id)

    def latest(self) -> Optional[DiscoveryRun]:
        return self._public().latest()
