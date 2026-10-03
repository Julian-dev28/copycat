"""`python -m api` entrypoint: reads env, builds the app, runs uvicorn on
COPYCAT_BIND:COPYCAT_API_PORT.
"""
from __future__ import annotations

import uvicorn

from .config import Config
from .main import create_app


def main() -> None:
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
