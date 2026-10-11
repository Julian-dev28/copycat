"""Async HTTP client for the copycat api, with errors phrased for an LLM.

Every failure becomes `ApiError(message)`, where the message says what to do
next ("set COPYCAT_API_TOKEN", "start copycat"). The server turns it into an
MCP `ToolError`, so Claude reads the message instead of a stack trace.

Status mapping:
  connect error / timeout  -> "start copycat"
  401                      -> "set COPYCAT_API_TOKEN" (the api's bearer auth is 401 only)
  403                      -> the api's own `detail` (a policy refusal, e.g. MCP trading off)
  410 / 429                -> the api's own `detail` (plan used/expired, rate limit)
  503                      -> "start copycat" (the api is up, its backing service is not)
  404 with FastAPI's bare "Not Found" -> the route does not exist in this api build
  other 4xx                -> the api's own `detail`
  202                      -> returned as data (`Accepted`), the caller decides
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .config import McpConfig

START_HINT = ("Start copycat first: `make dev` in the copycat repo (or `docker compose up -d`), "
              "then retry.")
TOKEN_HINT = ("Set COPYCAT_API_TOKEN to the api's token (in the MCP server env or the repo .env), "
              "or point COPYCAT_DATA_DIR at the data dir that holds api_token.")


class ApiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class RouteMissing(ApiError):
    """The api answered 404 for the route itself (not for a resource)."""


@dataclass
class Accepted:
    """A 202: the resource is being built. `body` is usually a ScoutStatus."""
    body: Any


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:500] or resp.reason_phrase
    if isinstance(body, dict) and "detail" in body:
        d = body["detail"]
        return d if isinstance(d, str) else str(d)[:1000]
    return str(body)[:500]


class CopycatApi:
    def __init__(self, config: McpConfig, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.config = config
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.config.api_url, timeout=self.config.timeout_s,
                                 transport=self._transport)

    async def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                      json: Any = None, timeout_s: Optional[float] = None) -> Any:
        """`timeout_s` overrides the config timeout for one slow call (a copy
        plan's live preview reads every coin he holds: ~40 s for 60+ coins)."""
        token = self.config.token()
        if not token:
            raise ApiError(f"No copycat api token found (looked at COPYCAT_API_TOKEN and "
                           f"{self.config.token_file}). {TOKEN_HINT}", status=401)
        if params:
            params = {k: v for k, v in params.items() if v is not None and v != []}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with self._client() as client:
                resp = await client.request(method, path, params=params, json=json, headers=headers,
                                            timeout=timeout_s or self.config.timeout_s)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ApiError(f"copycat api is not reachable at {self.config.api_url} ({type(e).__name__}). "
                           f"{START_HINT}") from e
        except httpx.TimeoutException as e:
            raise ApiError(f"copycat api at {self.config.api_url} timed out on {method} {path}. "
                           f"It may be busy; retry, or check its logs.") from e
        except httpx.HTTPError as e:
            raise ApiError(f"HTTP error talking to copycat api: {e}") from e
        return self._handle(method, path, resp)

    def _handle(self, method: str, path: str, resp: httpx.Response) -> Any:
        s = resp.status_code
        if s == 202:
            return Accepted(resp.json() if resp.content else None)
        if 200 <= s < 300:
            return resp.json() if resp.content else None
        detail = _detail(resp)
        where = f"{method} {path}"
        if s == 401:
            raise ApiError(f"copycat api rejected the token ({s} on {where}). {TOKEN_HINT}", status=s)
        if s == 403:
            raise ApiError(f"copycat api refused ({s} on {where}): {detail}", status=s)
        if s == 410:
            raise ApiError(f"Gone ({where}): {detail}", status=s)
        if s == 429:
            raise ApiError(f"Rate limited ({where}): {detail}", status=s)
        if s == 503:
            raise ApiError(f"copycat api answered 503 on {where}: {detail}. A backing copycat service "
                           f"is not running. {START_HINT}", status=s)
        if s == 404 and detail == "Not Found":
            raise RouteMissing(f"{where} does not exist in this copycat api build (404 Not Found). "
                               f"Update copycat to a version that has this route.", status=s)
        if s == 404:
            raise ApiError(f"Not found ({where}): {detail}", status=s)
        if s == 409:
            raise ApiError(f"Busy or conflict ({where}): {detail}", status=s)
        if s in (400, 422):
            raise ApiError(f"copycat api refused the request ({s} on {where}): {detail}", status=s)
        raise ApiError(f"copycat api error {s} on {where}: {detail}", status=s)
