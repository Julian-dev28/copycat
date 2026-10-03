from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from contracts.models import EngineEvent, EngineStatus, Settings

from ..deps import get_engine_client, get_store, require_auth
from ..engine_client import EngineClient, EngineUnavailable
from ..schemas import SettingsPatch
from ..settings_store import SettingsStore

router = APIRouter(prefix="/api", tags=["engine"], dependencies=[Depends(require_auth)])


@router.get("/status", response_model=EngineStatus)
def get_status(engine: EngineClient = Depends(get_engine_client)) -> EngineStatus:
    try:
        return engine.status()
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


@router.get("/events", response_model=List[EngineEvent])
def get_events(
    limit: int = 100,
    since_ms: Optional[int] = None,
    engine: EngineClient = Depends(get_engine_client),
) -> List[EngineEvent]:
    try:
        return engine.events(limit, since_ms)
    except EngineUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


@router.post("/engine/halt", response_model=Settings)
def halt(store: SettingsStore = Depends(get_store)) -> Settings:
    """Flips `enabled` false. Exits already open keep mirroring -- the
    engine, not the api, decides what "halted" means for open positions;
    this route's only job is the settings flip.
    """
    return store.patch(SettingsPatch(enabled=False))
