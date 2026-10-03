"""Env-driven configuration. `Config.from_env()` reads COPYCAT_* (see
.env.example); `create_app()` always takes an explicit Config in tests so
no test ever touches real env vars or the repo's real ./data dir.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

API_VERSION = "0.1.0"

DEFAULT_BIND = "127.0.0.1"
DEFAULT_API_PORT = 8787
DEFAULT_WEB_ORIGIN = "http://localhost:3000"
DEFAULT_DATA_DIR = "./data"
DEFAULT_SSE_POLL_S = 0.2

LOCALHOST_BIND = "127.0.0.1"


@dataclass
class Config:
    data_dir: Path = Path(DEFAULT_DATA_DIR)
    api_token: Optional[str] = None
    bind: str = DEFAULT_BIND
    api_port: int = DEFAULT_API_PORT
    web_origin: str = DEFAULT_WEB_ORIGIN
    sse_poll_s: float = DEFAULT_SSE_POLL_S

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            data_dir=Path(os.environ.get("COPYCAT_DATA_DIR", DEFAULT_DATA_DIR)),
            api_token=os.environ.get("COPYCAT_API_TOKEN") or None,
            bind=os.environ.get("COPYCAT_BIND", DEFAULT_BIND),
            api_port=int(os.environ.get("COPYCAT_API_PORT", DEFAULT_API_PORT)),
            web_origin=os.environ.get("COPYCAT_WEB_ORIGIN", DEFAULT_WEB_ORIGIN),
            sse_poll_s=float(os.environ.get("COPYCAT_SSE_POLL_S", DEFAULT_SSE_POLL_S)),
        )

    def validate_or_raise(self) -> None:
        """The api refuses to start without a token unless it's bound to
        localhost only. Called once, inside create_app(), so both the real
        entrypoint (python -m api) and every test go through the same gate.
        """
        if not self.api_token and self.bind != LOCALHOST_BIND:
            raise RuntimeError(
                "COPYCAT_API_TOKEN is not set and COPYCAT_BIND "
                f"({self.bind!r}) is not {LOCALHOST_BIND!r}: refusing to "
                "start an unauthenticated api on a non-localhost bind. Set "
                "COPYCAT_API_TOKEN, or set COPYCAT_BIND=127.0.0.1 for "
                "localhost-only dev."
            )
