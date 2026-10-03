"""Fixtures. The FakeVenue and addresses live in engine_fakes.py so test
modules can import them by an absolute, collision-free name."""
from __future__ import annotations

import pytest

from engine_fakes import *  # noqa: F401,F403
from engine_fakes import FakeVenue  # noqa: F401
from engine.state import EngineState  # noqa: F401


@pytest.fixture
def venue() -> FakeVenue:
    return FakeVenue()


@pytest.fixture
def engine_state(tmp_path):
    with EngineState(tmp_path / "engine.db") as s:
        yield s
