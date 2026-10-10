"""Env-driven configuration for the copycat MCP server.

The server is a thin HTTP client of the copycat api. It needs exactly two
things: where the api is, and its bearer token. It never needs, reads or
keeps the Hyperliquid agent key:

  - `COPYCAT_AGENT_KEY` is popped from this process's env at startup, so
    nothing it imports (and no child it might spawn) can see it.
  - `.env` is read with `dotenv_values` (a dict), never `load_dotenv`, and
    only the keys in `_DOTENV_KEYS` are taken from it. The agent key in
    `.env` never enters `os.environ`.

Sources, first hit wins:
  api url : COPYCAT_API_URL, else http://localhost:$COPYCAT_API_PORT (env, then .env), else :8787
  token   : COPYCAT_API_TOKEN (env, then .env), else $COPYCAT_DATA_DIR/api_token
  data dir: COPYCAT_DATA_DIR (env, then .env), else ./data; relative paths are
            resolved against the repo root, not the cwd (Claude Code launches
            the server from wherever the user happens to be)

The token file is re-read on every request when no env token is set, so
starting the MCP server before the api (which generates the file) works.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API_PORT = 8787
TOKEN_FILE = "api_token"
DEFAULT_AUTHOR = "claude-code via copycat MCP"
DEFAULT_TIMEOUT_S = 30.0
# Opt-in for the one money-moving tool (execute_copy_plan). Read from the MCP
# server's own process env ONLY, never from .env: the api reads the same name
# from its env/.env for its own guard, and the two must be switched on separately.
ALLOW_TRADING_ENV = "COPYCAT_MCP_ALLOW_TRADING"

# The only .env keys this server reads. COPYCAT_AGENT_KEY is deliberately absent.
_DOTENV_KEYS = ("COPYCAT_API_URL", "COPYCAT_API_PORT", "COPYCAT_API_TOKEN", "COPYCAT_DATA_DIR",
                "COPYCAT_MCP_AUTHOR")


def scrub_agent_key(environ: "os._Environ[str] | Dict[str, str]" = os.environ) -> bool:
    """Drop the trading key from the process env. Returns True if it was there."""
    return environ.pop("COPYCAT_AGENT_KEY", None) is not None


def read_dotenv(path: Path) -> Dict[str, str]:
    """Allowlisted keys from `.env`, without touching os.environ."""
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:          # python-dotenv is a project dep; tolerate its absence anyway
        return {}
    raw = dotenv_values(path)
    return {k: v for k, v in raw.items() if k in _DOTENV_KEYS and v}


@dataclass
class McpConfig:
    api_url: str
    env_token: Optional[str]
    data_dir: Path
    author: str = DEFAULT_AUTHOR
    timeout_s: float = DEFAULT_TIMEOUT_S
    allow_trading: bool = False      # registers execute_copy_plan; env COPYCAT_MCP_ALLOW_TRADING=1 only

    @property
    def token_file(self) -> Path:
        return self.data_dir / TOKEN_FILE

    def token(self) -> Optional[str]:
        """Current bearer token, or None if neither source has one yet."""
        if self.env_token:
            return self.env_token
        try:
            t = self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return t or None

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None,
                 dotenv_path: Optional[Path] = None) -> "McpConfig":
        env = dict(os.environ if environ is None else environ)
        dotenv: Dict[str, str] = {}
        if env.get("COPYCAT_SKIP_DOTENV") != "1":
            dotenv = read_dotenv(dotenv_path or REPO_ROOT / ".env")

        def get(key: str) -> Optional[str]:
            v = env.get(key) or dotenv.get(key)
            return v.strip() if v and v.strip() else None

        url = get("COPYCAT_API_URL")
        if not url:
            port = get("COPYCAT_API_PORT") or str(DEFAULT_API_PORT)
            url = f"http://localhost:{port}"
        data_dir = Path(get("COPYCAT_DATA_DIR") or "./data").expanduser()
        if not data_dir.is_absolute():
            data_dir = (REPO_ROOT / data_dir).resolve()
        return cls(
            api_url=url.rstrip("/"),
            env_token=get("COPYCAT_API_TOKEN"),
            data_dir=data_dir,
            author=get("COPYCAT_MCP_AUTHOR") or DEFAULT_AUTHOR,
            allow_trading=(env.get(ALLOW_TRADING_ENV) or "").strip() == "1",
        )
