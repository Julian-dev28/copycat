from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from contracts.models import DiscoveryRun

from ..deps import get_discovery_client, get_store, require_auth
from ..discovery_client import DiscoveryBusy, DiscoveryClient, DiscoveryUnavailable
from ..schemas import DiscoveryRunRequest, DiscoveryRunResponse
from ..settings_store import SettingsStore

router = APIRouter(prefix="/api/discovery", tags=["discovery"], dependencies=[Depends(require_auth)])


@router.post("/runs", response_model=DiscoveryRunResponse)
def start_run(
    body: DiscoveryRunRequest,
    store: SettingsStore = Depends(get_store),
    discovery: DiscoveryClient = Depends(get_discovery_client),
) -> DiscoveryRunResponse:
    settings = body.settings if body.settings is not None else store.load()
    try:
        run_id = discovery.start_run(settings, body.sim_equity_usd, body.top_n)
    except DiscoveryBusy as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except DiscoveryUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return DiscoveryRunResponse(run_id=run_id)


# registered before /runs/{run_id} so "latest" is never captured as an id
@router.get("/runs/latest", response_model=DiscoveryRun)
def get_latest_run(discovery: DiscoveryClient = Depends(get_discovery_client)) -> DiscoveryRun:
    try:
        run = discovery.latest()
    except DiscoveryUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no discovery run yet")
    return run


@router.get("/runs/{run_id}", response_model=DiscoveryRun)
def get_run(run_id: str, discovery: DiscoveryClient = Depends(get_discovery_client)) -> DiscoveryRun:
    try:
        run = discovery.get_run(run_id)
    except DiscoveryUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no discovery run {run_id}") from e
    if run is None:  # discovery.public.get_run returns None for an unknown id
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no discovery run {run_id}")
    return run
