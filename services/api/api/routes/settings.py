from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.models import Settings

from ..deps import get_store, require_auth
from ..schemas import SettingsPatch
from ..settings_store import SettingsStore

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(require_auth)])


@router.get("/settings", response_model=Settings)
def get_settings(store: SettingsStore = Depends(get_store)) -> Settings:
    return store.load()


@router.put("/settings", response_model=Settings)
def put_settings(body: Settings, store: SettingsStore = Depends(get_store)) -> Settings:
    return store.put(body)


@router.patch("/settings", response_model=Settings)
def patch_settings(body: SettingsPatch, store: SettingsStore = Depends(get_store)) -> Settings:
    return store.patch(body)
