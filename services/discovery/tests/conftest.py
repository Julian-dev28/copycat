from __future__ import annotations

import sqlite3

import pytest

from discovery import db as discovery_db


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return discovery_db.connect(tmp_path / "discovery_test.db")
