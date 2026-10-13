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
    # httpx logs every request at INFO; that is noise in Claude Code's MCP log.
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = McpConfig.from_env()
    token_src = config.token_source()
    from contracts import build
    b = build.record("mcp")
    print(f"copycat-mcp: api {config.api_url}, token from {token_src}, build {b['build']} "
          f"(contract v{b['contract_version']})", file=sys.stderr)

    if token_src.endswith("(admin)"):
        print("copycat-mcp: WARNING using the ADMIN api token. Restart the copycat api so it "
              f"generates {config.mcp_token_file} (the scoped MCP token, audit H3).", file=sys.stderr)

    from .server import build_server
    build_server(config).run("stdio")


if __name__ == "__main__":
    main()
