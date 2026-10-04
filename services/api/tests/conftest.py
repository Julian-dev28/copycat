from __future__ import annotations

from pathlib import Path

import pytest
from api.config import Config
from api.deps import (
    get_discovery_client,
    get_engine_client,
    get_market_client,
    get_scout_client,
    get_thesis_client,
)
from api.fingerprint_jobs import FingerprintJobs
from api.main import create_app
from api_fakes import (
    OUR_ADDRESS,
    FakeDiscoveryClient,
    FakeEngineClient,
    FakeMarketClient,
    FakeScoutClient,
    FakeThesisClient,
)
from fastapi.testclient import TestClient

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
def fake_scout() -> FakeScoutClient:
    return FakeScoutClient()


@pytest.fixture
def fake_thesis() -> FakeThesisClient:
    return FakeThesisClient()


@pytest.fixture
def fake_market() -> FakeMarketClient:
    return FakeMarketClient()


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def jobs(clock: Clock) -> FingerprintJobs:
    """No worker thread: tests run queued fingerprints with jobs.drain()."""
    return FingerprintJobs(autostart=False, clock=clock, max_pending=3)


@pytest.fixture
def app(config: Config, fake_engine: FakeEngineClient, fake_discovery: FakeDiscoveryClient,
        fake_scout: FakeScoutClient, fake_thesis: FakeThesisClient, fake_market: FakeMarketClient,
        jobs: FingerprintJobs):
    application = create_app(config)
    application.state.fingerprint_jobs = jobs
    application.dependency_overrides[get_thesis_client] = lambda: fake_thesis
    application.dependency_overrides[get_market_client] = lambda: fake_market
    application.dependency_overrides[get_scout_client] = lambda: fake_scout
    application.dependency_overrides[get_engine_client] = lambda: fake_engine
    application.dependency_overrides[get_discovery_client] = lambda: fake_discovery
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


# ── /api/accounts (vault-backed): real vault in data_dir, fake HL, fake reads ──

@pytest.fixture
def hlfake(monkeypatch, data_dir):
    from accounts_fakes import FakeHL
    from vault import agents, approval, hlops
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("COPYCAT_NETWORK", "mainnet")
    monkeypatch.setenv("COPYCAT_SKIP_DOTENV", "1")
    monkeypatch.delenv("COPYCAT_ENV_FILE", raising=False)
    monkeypatch.delenv("COPYCAT_AGENT_KEY", raising=False)
    fake = FakeHL()
    monkeypatch.setattr(hlops, "extra_agents", fake.extra_agents)
    monkeypatch.setattr(hlops, "post_signed_action", fake.post_signed_action)
    monkeypatch.setattr(approval, "_sleep", lambda s: None)
    agents.invalidate()
    yield fake
    agents.invalidate()


@pytest.fixture
def backend(app):
    from accounts_fakes import FakeBackend
    from api.routes.accounts_common import get_accounts_backend
    b = FakeBackend()
    app.dependency_overrides[get_accounts_backend] = lambda: b
    return b


@pytest.fixture
def logs(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    return caplog
