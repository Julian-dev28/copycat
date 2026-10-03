"""Exports the OpenAPI schema to services/api/openapi.json. Run via
`make openapi` (or `python -m api.openapi_export`). tests/test_openapi.py
regenerates the schema the same way and diffs it against the committed
file, so a route change that forgets to re-run this fails the gate.

Schema content never depends on data_dir/token/bind values -- only route
signatures do -- so this builds the app against a throwaway temp dir
rather than real env/config, and never touches the repo's ./data.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .config import Config
from .main import create_app


def build_schema() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(
            data_dir=Path(tmp),
            api_token="openapi-export-placeholder",
            bind="0.0.0.0",
            web_origin="http://localhost:3000",
        )
        app = create_app(config)
        return app.openapi()


def main() -> None:
    schema = build_schema()
    out_path = Path(__file__).resolve().parents[1] / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
