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

import os
from typing import List, Optional, Protocol

from contracts.models import EngineEvent, EngineStatus, Settings, WalletCopyRequest, WalletPreview


class EngineUnavailable(RuntimeError):
    """engine.public isn't importable: services/engine isn't built yet, or
    this process can't see it (e.g. PYTHONPATH not set). Routes map this to
    HTTP 503, not a crash.
    """


class PreviewFailed(RuntimeError):
    """The leader's live read failed during a preview. Routes map this to 502."""


class EngineClient(Protocol):
    def status(self) -> EngineStatus: ...

    def events(self, limit: int, since_ms: Optional[int] = None) -> List[EngineEvent]: ...

    def preview(self, address: str, req: WalletCopyRequest, settings: Settings) -> WalletPreview: ...


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

    def preview(self, address: str, req: WalletCopyRequest, settings: Settings) -> WalletPreview:
        """`engine.public.preview_wallet`: a few live HL reads (his account,
        24h volume, book depth) in this process. The api never has the agent
        key, and the first preview flips the process to background HL
        priority so it never spends the engine's rate reserve (same as
        api.scout_client)."""
        public = self._public()
        fn = getattr(public, "preview_wallet", None)
        if fn is None:
            raise EngineUnavailable("engine.public has no preview_wallet() yet")
        os.environ["COPYCAT_HL_PRIORITY"] = "background"
        failed = getattr(public, "PreviewUnavailable", None)
        try:
            return fn(address, req, settings)
        except Exception as e:
            if isinstance(failed, type) and isinstance(e, failed):
                raise PreviewFailed(str(e)) from e
            raise
