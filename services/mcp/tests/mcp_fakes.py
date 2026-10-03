"""Test helpers: a fake copycat api (httpx.MockTransport) and an in-process MCP client."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import anyio
import httpx
from copycat_mcp.api_client import CopycatApi
from copycat_mcp.config import McpConfig
from copycat_mcp.server import build_server
from mcp import Client

TOKEN = "t" * 64
ADDR = "0x" + "ab" * 20
ADDR_MIXED = "0x" + "AB" * 20

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeApi:
    """Records every request; answers from `routes[(method, path)]` or 404 Not Found."""
    routes: Dict[Tuple[str, str], Any] = field(default_factory=dict)
    requests: List[httpx.Request] = field(default_factory=list)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        r = self.routes.get((req.method, req.url.path))
        if r is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        if callable(r):
            return r(req)
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(200, json=r)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self) -> Any:
        return json.loads(self.last.content)


def make_server(fake: Optional[Handler] = None, *, token: Optional[str] = TOKEN,
                data_dir: Path = Path("/nonexistent-copycat-data"), raise_connect: bool = False):
    def handler(req: httpx.Request) -> httpx.Response:
        if raise_connect:
            raise httpx.ConnectError("refused", request=req)
        return fake(req)  # type: ignore[misc]
    cfg = McpConfig(api_url="http://localhost:8795", env_token=token, data_dir=data_dir)
    api = CopycatApi(cfg, transport=httpx.MockTransport(handler))
    return build_server(cfg, api)


def run(server, fn):
    """Open an in-process MCP client on `server` and run `await fn(client)`."""
    async def main():
        async with Client(server) as client:
            return await fn(client)
    return anyio.run(main)


def call(server, name: str, args: Optional[Dict[str, Any]] = None):
    return run(server, lambda c: c.call_tool(name, args or {}))


def text(result) -> str:
    return "\n".join(getattr(b, "text", "") for b in result.content)
