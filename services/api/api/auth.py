"""Bearer auth, two tokens (audit H3).

  admin token (data/api_token, COPYCAT_API_TOKEN): every route. The web UI.
  MCP token   (data/mcp_token, COPYCAT_MCP_TOKEN): only MCP_SCOPE below; any
              other route is 403. The copycat MCP server uses it, so the MCP
              path itself cannot turn trading on, change settings, copy or stop
              a wallet with arbitrary terms, close positions, touch accounts or
              keys, or read the pending plans' confirm codes.

The scope is matched on the ROUTE TEMPLATE FastAPI resolved for the request
(`request.scope["route"].path`), never on the raw URL, so path tricks
(`/api/scout/../settings`, encoded slashes, a trailing slash) cannot widen it.

Honest limit: Claude Code runs as the user and can read files, including
data/api_token. The real boundary against a prompt-injected session is Claude
Code's own permission prompts (never auto-allow shell/file reads of data/).
The scoped token only stops the MCP tools from escalating.

If no token is configured (only in tests that build BearerAuth directly),
auth is a no-op.
"""
from __future__ import annotations

import hmac
from typing import FrozenSet, Optional, Tuple

from fastapi import HTTPException, Request, status

# (method, route template). Reads the MCP tools need, the thesis write, the
# engine preview (computes only), and the plan create/execute pair. NOT here,
# on purpose: GET /api/mcp/plans/pending (the confirm codes: human only),
# /api/leaders, PUT/PATCH /api/settings, /api/wallets/{a}/copy|stop|pause|...,
# /api/engine/*, /api/accounts/*, /api/discovery POSTs, /api/scout/refresh, what-if.
MCP_SCOPE: FrozenSet[Tuple[str, str]] = frozenset({
    ("GET", "/api/scout/traders"),
    ("GET", "/api/scout/traders/{address}"),
    ("GET", "/api/scout/traders/{address}/fingerprint"),
    ("GET", "/api/scout/traders/{address}/trades"),
    ("GET", "/api/scout/traders/{address}/fills"),
    ("GET", "/api/scout/traders/{address}/orders"),
    ("GET", "/api/scout/traders/{address}/thesis"),
    ("PUT", "/api/scout/traders/{address}/thesis"),
    ("GET", "/api/scout/presets"),
    ("GET", "/api/scout/status"),
    ("GET", "/api/market/candles"),
    ("GET", "/api/settings"),
    ("GET", "/api/status"),
    ("GET", "/api/events"),
    ("GET", "/api/wallets"),
    ("GET", "/api/wallets/{address}/events"),
    ("GET", "/api/wallets/{address}/projection"),
    ("POST", "/api/wallets/{address}/preview"),
    ("POST", "/api/mcp/plans"),
    ("POST", "/api/mcp/plans/{plan_id}/execute"),
})


def _route_key(request: Request) -> Optional[Tuple[str, str]]:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return (request.method.upper(), path) if path else None


def _eq(a: str, b: str) -> bool:
    # bytes: compare_digest raises TypeError on non-ASCII str (a 500, not a 401)
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class BearerAuth:
    def __init__(self, token: Optional[str], mcp_token: Optional[str] = None):
        self.token = token
        self.mcp_token = mcp_token

    def __call__(self, request: Request) -> None:
        if not self.token:
            return
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        # constant-time compare: a timing side-channel on token length/prefix
        # is exactly the kind of leak a trading-bot auth token can't afford.
        if _eq(value, self.token):
            return
        if self.mcp_token and _eq(value, self.mcp_token):
            if _route_key(request) in MCP_SCOPE:
                request.state.token_scope = "mcp"
                return
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "the MCP token cannot use this route (scoped to research reads, "
                                "theses, wallet preview and MCP plans); the user does this in the "
                                "copycat web UI")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")
