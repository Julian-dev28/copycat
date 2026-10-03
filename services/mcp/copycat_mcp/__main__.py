"""`python -m copycat_mcp`: the copycat MCP server on stdio.

stdout is the MCP channel; never print to it. Diagnostics go to stderr.
"""
from __future__ import annotations

import sys

from .config import McpConfig, scrub_agent_key


def main() -> None:
    # The trading key has no business in this process. Drop it before
    # anything else is imported or spawned.
    scrub_agent_key()
    config = McpConfig.from_env()
    token_src = "COPYCAT_API_TOKEN" if config.env_token else str(config.token_file)
    print(f"copycat-mcp: api {config.api_url}, token from {token_src}", file=sys.stderr)

    from .server import build_server
    build_server(config).run("stdio")


if __name__ == "__main__":
    main()
