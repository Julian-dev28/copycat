"""Adapter in front of services/engine's public surface (`engine.public`).

services/engine is being built in parallel by another session. We import it
lazily, inside each call, instead of at module load time, for two reasons:
1. the api must be importable and every non-engine route must work even
   before services/engine exists or while it's mid-build.
2. a fresh engine build is picked up on the next call with no api restart.

Routes depend on the `EngineClient` Protocol (via api.deps.get_engine_client)
and tests inject a fake that implements it -- they never import `engine`.
"""
from __future__ import annotations

from typing import List, Optional, Protocol

from contracts.models import EngineEvent, EngineStatus


class EngineUnavailable(RuntimeError):
    """engine.public isn't importable: services/engine isn't built yet, or
    this process can't see it (e.g. PYTHONPATH not set). Routes map this to
    HTTP 503, not a crash.
    """


class EngineClient(Protocol):
    def status(self) -> EngineStatus: ...

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]: ...


class RealEngineClient:
    """Implements EngineClient by calling engine.public, imported lazily."""

    @staticmethod
    def _public():
        try:
            from engine import public  # type: ignore[import-not-found]
        except ImportError as e:
            raise EngineUnavailable(
                f"services/engine isn't importable yet: {e}"
            ) from e
        return public

    def status(self) -> EngineStatus:
        return self._public().status()

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]:
        return self._public().events(limit, since_ms)
