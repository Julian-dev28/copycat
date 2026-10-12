"""The FastAPI app. create_app() is the single place that wires config ->
store/auth/clients -> middleware -> routers, used by both the real
entrypoint (api.__main__) and every test (each test builds its own app from
its own Config).

`api.main:app` still works for `uvicorn api.main:app`, but is built lazily
on first attribute access (module `__getattr__`), not at import: building it
resolves the api token, which may generate `data/api_token`, and importing
this module from a test must never write into the repo's ./data.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from contracts import build as build_mod

from .auth import BearerAuth
from .config import API_VERSION, Config
from .discovery_client import RealDiscoveryClient
from .engine_client import RealEngineClient
from .errors import register_exception_handlers
from .fingerprint_jobs import FingerprintJobs
from .market_client import RealMarketClient
from .routes import accounts as accounts_routes
from .routes import (
    accounts_common,
    accounts_funding,
    accounts_onboard,
    discovery,
    engine,
    events_stream,
    health,
    market,
    mcp_plans,
    scout,
    thesis,
    wallets,
)
from .routes import leaders as leaders_routes
from .routes import settings as settings_routes
from .scout_client import RealScoutClient
from .settings_store import SettingsStore
from .thesis_client import RealThesisClient


def create_app(config: Optional[Config] = None) -> FastAPI:
    # The api never signs anything. `make dev` runs load_dotenv() in
    # api.__main__, which would otherwise leave the agent's private key in
    # this process's environment (and in every subprocess it spawns, such as
    # discovery runs). Drop it before anything else happens.
    os.environ.pop("COPYCAT_AGENT_KEY", None)

    config = config or Config.from_env()
    config.validate_or_raise()

    app = FastAPI(title="copycat api", version=API_VERSION)
    app.state.config = config
    # version-skew guard: this process's build, compared with the engine's and
    # scout's in GET /api/health (contracts.build)
    app.state.build = build_mod.record("api")
    app.state.store = SettingsStore(config.data_dir, config.our_address)
    app.state.auth = BearerAuth(config.api_token, config.mcp_token)
    # factories, not instances: each request gets a fresh client so a
    # lazily-imported engine/discovery module reload is picked up.
    app.state.engine_client_factory = RealEngineClient
    app.state.discovery_client_factory = lambda: RealDiscoveryClient(config.data_dir)
    app.state.scout_client_factory = RealScoutClient
    # POST /api/scout/traders/{address}/what-if runs one at a time per api
    # process; a second concurrent request is 409 (api.routes.scout).
    app.state.scout_what_if_lock = threading.Lock()
    app.state.thesis_client_factory = lambda: RealThesisClient(config.data_dir)
    app.state.market_client_factory = RealMarketClient
    # slow fingerprint computes: one at a time, in a child process, cached 15 min
    app.state.fingerprint_jobs = FingerprintJobs()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.web_origin],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # DNS rebinding guard: a page on evil.com that resolves to 127.0.0.1
    # still sends `Host: evil.com`, and gets a 400 here before any route.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))

    register_exception_handlers(app)
    # /api/accounts: vault-backed trading accounts (and a 422 handler that never echoes secrets)
    accounts_common.register(app)

    app.include_router(health.router)
    app.include_router(settings_routes.router)
    app.include_router(leaders_routes.router)
    app.include_router(engine.router)
    app.include_router(events_stream.router)
    app.include_router(discovery.router)
    app.include_router(scout.router)
    app.include_router(thesis.router)
    app.include_router(market.router)
    app.include_router(wallets.router)
    app.include_router(mcp_plans.router)       # MCP copy plans (execute is env-gated)
    app.include_router(accounts_onboard.router)   # before accounts: fixed paths win over /{id}
    app.include_router(accounts_routes.router)
    app.include_router(accounts_funding.router)

    return app


_app: Optional[FastAPI] = None


def __getattr__(name: str) -> Any:
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
