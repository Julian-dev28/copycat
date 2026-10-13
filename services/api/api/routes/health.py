"""GET /api/health. The one route with no auth dependency -- see
docs/ARCHITECTURE.md: "on every route except GET /api/health".

Also the version-skew guard (audit M12, api.build_skew): every long-running
process's build and the ones running other code than this api. Every probe
is best effort: health never fails because the engine or scout is down.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request

from contracts.models import CONTRACT_VERSION

from .. import build_skew
from ..config import API_VERSION
from ..schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])
logger = logging.getLogger(__name__)


def _engine_build(request: Request) -> Tuple[Optional[Dict[str, Any]], bool]:
    try:
        client = request.app.state.engine_client_factory()
        public = client._public()
        b = public.process_build() if hasattr(public, "process_build") else None
        if b is not None:
            return b, bool(b.get("alive"))
        return None, bool(client.status().running)      # alive on code older than the guard
    except Exception:
        logger.debug("engine build probe failed", exc_info=True)
        return None, False


def _scout_build(request: Request) -> Tuple[Optional[Dict[str, Any]], bool]:
    try:
        public = request.app.state.scout_client_factory()._public()
        b = public.scout_build() if hasattr(public, "scout_build") else None
        return b, bool(b and b.get("alive"))
    except Exception:
        logger.debug("scout build probe failed", exc_info=True)
        return None, False


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    api_b = getattr(request.app.state, "build", None) or {}
    api = build_skew.component("api", api_b, True)
    others = [build_skew.component("engine", *_engine_build(request)),
              build_skew.component("scout", *_scout_build(request))]
    return HealthResponse(ok=True, version=API_VERSION, contract_version=CONTRACT_VERSION,
                          builds=[api, *others], stale=build_skew.stale(api, others))
