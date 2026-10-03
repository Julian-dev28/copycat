"""The web agent generates TS types from services/api/openapi.json, so a
route/schema change that forgets to re-run `make openapi` has to fail the
gate, not surface later as a silent type drift in the web app.
"""
from __future__ import annotations

import json
from pathlib import Path

from api.openapi_export import build_schema

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def test_openapi_json_exists() -> None:
    assert OPENAPI_PATH.exists(), "run `make openapi` to generate services/api/openapi.json"


def test_openapi_schema_is_current() -> None:
    committed = json.loads(OPENAPI_PATH.read_text())
    current = build_schema()
    assert current == committed, (
        "services/api/openapi.json is stale. Run `make openapi` and commit the result."
    )


def test_openapi_has_every_documented_route() -> None:
    schema = build_schema()
    paths = schema["paths"]
    expected = {
        ("GET", "/api/health"),
        ("GET", "/api/settings"),
        ("PUT", "/api/settings"),
        ("PATCH", "/api/settings"),
        ("POST", "/api/leaders"),
        ("DELETE", "/api/leaders/{address}"),
        ("GET", "/api/status"),
        ("GET", "/api/events"),
        ("GET", "/api/events/stream"),
        ("POST", "/api/engine/halt"),
        ("POST", "/api/engine/close-all"),
        ("POST", "/api/discovery/runs"),
        ("GET", "/api/discovery/runs/latest"),
        ("GET", "/api/discovery/runs/{run_id}"),
    }
    actual = {
        (method.upper(), path) for path, methods in paths.items() for method in methods
    }
    assert expected <= actual, expected - actual
