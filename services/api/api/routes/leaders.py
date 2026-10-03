from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from contracts.models import Settings

from ..deps import get_store, require_auth
from ..schemas import AddLeaderRequest
from ..settings_store import LeaderLimitError, SettingsStore

router = APIRouter(prefix="/api/leaders", tags=["leaders"], dependencies=[Depends(require_auth)])


@router.post("", response_model=Settings)
def add_leader(body: AddLeaderRequest, store: SettingsStore = Depends(get_store)) -> Settings:
    try:
        return store.add_leader(body.address)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except LeaderLimitError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.delete("/{address}", response_model=Settings)
def delete_leader(address: str, store: SettingsStore = Depends(get_store)) -> Settings:
    return store.remove_leader(address)
