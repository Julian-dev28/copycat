"""A merged PATCH/leader mutation can fail contracts.models.Settings
validation (e.g. a range violation) after it's already past FastAPI's own
request-body validation. That raises pydantic.ValidationError, which this
handler turns into the same readable 422 shape FastAPI's own
RequestValidationError uses, so clients see one consistent error format.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .settings_store import OwnAddressError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValidationError)
    async def _on_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(OwnAddressError)
    async def _on_own_address(request: Request, exc: OwnAddressError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
