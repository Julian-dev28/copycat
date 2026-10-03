"""GET /api/events/stream: tail data/events.jsonl over SSE.

This tails the file directly, independent of engine.public -- so the
stream works even if the engine process/module isn't up, and it stays a
thin passthrough: each appended line goes out as one SSE `data` field
as-is, with no re-parse/re-validate of the JSON on every poll. The shape
of each line (one contracts.models.EngineEvent per docs/ARCHITECTURE.md)
is the engine's contract to uphold, not something the api re-checks here.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ..config import Config
from ..deps import get_config, require_auth
from ..events_tail import read_new_lines, start_offset

router = APIRouter(prefix="/api", tags=["events"], dependencies=[Depends(require_auth)])


async def event_generator(path: Path, poll_s: float, request: Request) -> AsyncIterator[Dict[str, str]]:
    """The actual tail loop, factored out of the route so it's directly
    callable (and testable) without going through an ASGI transport.

    httpx's ASGITransport -- which both direct httpx.AsyncClient usage and
    Starlette's TestClient are built on -- fully awaits the app callable
    before returning any response data, so it structurally can't drive an
    infinite SSE generator over a fake HTTP connection in tests. Tests
    instead call this function directly with a fake Request.
    """
    pos = start_offset(path)
    while True:
        if await request.is_disconnected():
            break
        pos, lines = read_new_lines(path, pos)
        for line in lines:
            yield {"event": "message", "data": line}
        await asyncio.sleep(poll_s)


@router.get("/events/stream")
async def events_stream(request: Request, config: Config = Depends(get_config)) -> EventSourceResponse:
    path = config.data_dir / "events.jsonl"
    return EventSourceResponse(event_generator(path, config.sse_poll_s, request))
