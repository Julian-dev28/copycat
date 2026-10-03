from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import Config
from api.deps import get_discovery_client, get_engine_client
from api.main import create_app

from api_fakes import OUR_ADDRESS, FakeDiscoveryClient, FakeEngineClient

TOKEN = "test-token-0123456789abcdef0123456789"   # >= 32 chars, like a real one


@pytest.fixture
def anyio_backend() -> str:
    """Pins the anyio pytest plugin to the asyncio backend for the handful
    of `@pytest.mark.anyio` async tests (SSE generator tests); we don't
    need/want trio installed just to satisfy anyio's default backend list.
    """
    return "asyncio"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def config(data_dir: Path) -> Config:
    return Config(
        data_dir=data_dir,
        api_token=TOKEN,
        bind="0.0.0.0",
        api_port=0,
        web_origin="http://localhost:3000",
        sse_poll_s=0.01,
        allowed_hosts=["localhost", "127.0.0.1", "testserver"],
        our_address=OUR_ADDRESS,
    )


@pytest.fixture
def fake_engine() -> FakeEngineClient:
    return FakeEngineClient()


@pytest.fixture
def fake_discovery() -> FakeDiscoveryClient:
    return FakeDiscoveryClient()


@pytest.fixture
def app(config: Config, fake_engine: FakeEngineClient, fake_discovery: FakeDiscoveryClient):
    application = create_app(config)
    application.dependency_overrides[get_engine_client] = lambda: fake_engine
    application.dependency_overrides[get_discovery_client] = lambda: fake_discovery
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}
