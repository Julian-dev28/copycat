"""FastAPI dependency functions. Everything pulls from app.state, which
create_app() populates, so tests can override per-request objects
(dependency_overrides) without touching env vars or real files.
"""
from __future__ import annotations

from fastapi import Request

from .config import Config
from .discovery_client import DiscoveryClient
from .engine_client import EngineClient
from .settings_store import SettingsStore


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_store(request: Request) -> SettingsStore:
    return request.app.state.store


def get_engine_client(request: Request) -> EngineClient:
    return request.app.state.engine_client_factory()


def get_discovery_client(request: Request) -> DiscoveryClient:
    return request.app.state.discovery_client_factory()


def require_auth(request: Request) -> None:
    request.app.state.auth(request)
