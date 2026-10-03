"""`python -m api` entrypoint: reads env, builds the app, runs uvicorn on
COPYCAT_BIND:COPYCAT_API_PORT.
"""
from __future__ import annotations

import os

import uvicorn

from .config import Config
from .main import create_app


def main() -> None:
    # COPYCAT_SKIP_DOTENV=1: never read ./.env (it holds the real agent key).
    # Every test or scratch run of this entrypoint sets it.
    if os.environ.get("COPYCAT_SKIP_DOTENV") != "1":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    config = Config.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.bind, port=config.api_port, log_level="info")


if __name__ == "__main__":
    main()
