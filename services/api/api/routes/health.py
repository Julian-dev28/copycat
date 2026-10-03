"""GET /api/health. The one route with no auth dependency -- see
docs/ARCHITECTURE.md: "on every route except GET /api/health".
"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import API_VERSION
from ..schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, version=API_VERSION)
