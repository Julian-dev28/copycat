"""Bearer auth. If no token is configured (only possible when bound to
127.0.0.1, enforced by Config.validate_or_raise), auth is a no-op: that's
the documented localhost-only dev mode.
"""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import HTTPException, Request, status


class BearerAuth:
    def __init__(self, token: Optional[str]):
        self.token = token

    def __call__(self, request: Request) -> None:
        if not self.token:
            return
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        # constant-time compare: a timing side-channel on token length/prefix
        # is exactly the kind of leak a trading-bot auth token can't afford.
        if not hmac.compare_digest(value, self.token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")
