"""The FastAPI app: `api.main:app`. create_app() is the single place that
wires config -> store/auth/clients -> middleware -> routers, used by both
the real entrypoint (api.__main__) and every test (each test builds its own
app from its own Config, never touching the module-level singleton below).
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import API_VERSION, Config
from .discovery_client import RealDiscoveryClient
from .engine_client import RealEngineClient
from .errors import register_exception_handlers
from .routes import discovery, engine, events_stream, health
from .routes import leaders as leaders_routes
from .routes import settings as settings_routes
from .settings_store import SettingsStore
from .auth import BearerAuth


def create_app(config: Optional[Config] = None) -> FastAPI:
    config = config or Config.from_env()
    config.validate_or_raise()

    app = FastAPI(title="copycat api", version=API_VERSION)
    app.state.config = config
    app.state.store = SettingsStore(config.data_dir)
    app.state.auth = BearerAuth(config.api_token)
    # factories, not instances: each request gets a fresh client so a
    # lazily-imported engine/discovery module reload is picked up.
    app.state.engine_client_factory = RealEngineClient
    app.state.discovery_client_factory = RealDiscoveryClient

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.web_origin],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(settings_routes.router)
    app.include_router(leaders_routes.router)
    app.include_router(engine.router)
    app.include_router(events_stream.router)
    app.include_router(discovery.router)

    return app


app = create_app()
