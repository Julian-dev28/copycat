"""Shared plumbing for the /api/accounts routers.

Secrets (passphrases, private keys) arrive in request bodies, go straight to
vault.public, and the local references are dropped when the handler returns.
Nothing here logs a body. A body that fails validation gets a 422 WITHOUT the
offending input echoed back (FastAPI's default handler would echo it).
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..accounts_backend import AccountsBackend
from ..attempt_limit import AttemptLimiter

T = TypeVar("T")
PREFIX = "/api/accounts"


def get_accounts_backend(request: Request) -> AccountsBackend:
    return request.app.state.accounts_backend_factory()


def get_attempt_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.attempt_limiter


def vault_call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a vault function; map VaultError to its HTTP status with its (secret-free) message."""
    from vault.errors import VaultError  # type: ignore[import-not-found]
    try:
        return fn(*args, **kwargs)
    except VaultError as exc:
        raise HTTPException(exc.http_status, str(exc)) from None


def register(app: FastAPI) -> None:
    app.state.accounts_backend_factory = AccountsBackend
    app.state.attempt_limiter = AttemptLimiter()

    @app.exception_handler(RequestValidationError)
    async def _scrubbed_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        if not request.url.path.startswith(PREFIX):
            return await request_validation_exception_handler(request, exc)
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))
