"""GET /api/events/stream tails data/events.jsonl like `tail -f`: starts at
end of file, streams appended lines over SSE, until the client disconnects.

This exercises api.routes.events_stream.event_generator directly (the exact
async generator the route hands to EventSourceResponse) rather than going
over a real HTTP connection. httpx's ASGITransport -- which both
httpx.AsyncClient and Starlette's TestClient are built on -- fully awaits
the ASGI app callable before returning any response data, so it can't
drive an infinite generator like this over a fake connection: the request
would hang forever waiting for a response that structurally never
completes. Calling the generator directly tests the real tail/poll logic
with no such impedance mismatch, and runs in milliseconds.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from api.routes.events_stream import event_generator

pytestmark = pytest.mark.anyio


class FakeRequest:
    """Only needs is_disconnected(), the one Request method the generator
    calls."""

    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def _anext_after_priming(gen) -> dict:
    """Start consuming the generator, then give it a moment to run past its
    `start_offset()` call and into its first sleep before the caller
    appends anything -- matching how a real client actually triggers this:
    EventSourceResponse starts iterating the generator the instant the
    connection is established, before any *new* event can possibly exist.

    An async generator's body does NOT run until first iterated (same rule
    as a sync generator), so without this priming step, calling
    `gen.__anext__()` AFTER a test has already appended a line would
    capture `start_offset()` as the post-append file size, treating that
    line as already-seen history -- exactly the bug this helper avoids.
    """
    task = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.05)
    return task


async def test_sse_does_not_replay_history(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"ts_ms": 1, "action": "baseline"}\n')
    gen = event_generator(path, poll_s=0.01, request=FakeRequest())

    task = await _anext_after_priming(gen)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts_ms": 2, "action": "open", "coin": "BTC"}\n')

    first = await asyncio.wait_for(task, timeout=2.0)
    assert first == {"event": "message", "data": '{"ts_ms": 2, "action": "open", "coin": "BTC"}'}


async def test_sse_emits_each_appended_line_in_order(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("")
    gen = event_generator(path, poll_s=0.01, request=FakeRequest())

    task = await _anext_after_priming(gen)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts_ms": 1, "action": "open"}\n')
    first = await asyncio.wait_for(task, timeout=2.0)
    assert first["data"] == '{"ts_ms": 1, "action": "open"}'

    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts_ms": 2, "action": "close"}\n')
    second = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert second["data"] == '{"ts_ms": 2, "action": "close"}'


async def test_sse_stops_on_disconnect(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("")
    request = FakeRequest()
    gen = event_generator(path, poll_s=0.01, request=request)

    request.disconnected = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=2.0)


def test_sse_route_requires_auth(client) -> None:
    """A rejected-by-auth request never reaches the infinite generator, so
    this is a normal fast HTTP round trip and safe to test over TestClient.
    """
    r = client.get("/api/events/stream")
    assert r.status_code == 401
