"""Env-driven configuration. `Config.from_env()` reads COPYCAT_* (see
.env.example); `create_app()` always takes an explicit Config in tests so
no test ever touches real env vars or the repo's real ./data dir.

The api ALWAYS requires a bearer token, on every bind. There is no
unauthenticated dev mode: a token-less api on 127.0.0.1 is still reachable
from any web page the user opens, via DNS rebinding (verified: a PATCH
/api/settings with `Host: evil.com:8787` got 200). Token sources, in order:
  1. COPYCAT_API_TOKEN, if non-empty. Must be >= 32 chars and not "change-me".
  2. $COPYCAT_DATA_DIR/api_token, if it exists (generated on an earlier start).
  3. Otherwise a fresh 64-hex-char token is generated into that file (mode
     0600) and its PATH (never the token) is printed.
A second, SCOPED token for the copycat MCP server (audit H3), same rules:
COPYCAT_MCP_TOKEN, else $COPYCAT_DATA_DIR/mcp_token (generated 0600). It can
only reach api.auth.MCP_SCOPE (research reads, thesis PUT, wallet preview, MCP
plan create/execute); every other route is 403 for it.
Host-header allowlisting (TrustedHostMiddleware, see main.py) is the second
DNS-rebinding guard: localhost, 127.0.0.1, plus COPYCAT_ALLOWED_HOSTS.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"

DEFAULT_BIND = "127.0.0.1"
DEFAULT_API_PORT = 8787
DEFAULT_WEB_ORIGIN = "http://localhost:3000"
DEFAULT_DATA_DIR = "./data"
DEFAULT_SSE_POLL_S = 0.2
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1")

LOCALHOST_BIND = "127.0.0.1"
MIN_TOKEN_LEN = 32
REJECTED_TOKENS = frozenset({"change-me", "changeme"})
TOKEN_FILE = "api_token"
MCP_TOKEN_FILE = "mcp_token"   # audit H3: the scoped token the MCP server uses (api.auth.MCP_SCOPE)


def check_token(token: str, source: str = "COPYCAT_API_TOKEN") -> None:
    if token.strip().lower() in REJECTED_TOKENS:
        raise RuntimeError(
            f"{source} is the placeholder {token!r}: refusing to start. Set a real token "
            f"(openssl rand -hex 32) or leave COPYCAT_API_TOKEN empty to have one generated "
            f"into $COPYCAT_DATA_DIR/{TOKEN_FILE}.")
    if len(token) < MIN_TOKEN_LEN:
        raise RuntimeError(
            f"{source} is {len(token)} chars, under the {MIN_TOKEN_LEN}-char minimum: refusing to "
            f"start. Use openssl rand -hex 32, or leave COPYCAT_API_TOKEN empty to have one "
            f"generated into $COPYCAT_DATA_DIR/{TOKEN_FILE}.")


def resolve_api_token(data_dir: Path, env_token: Optional[str], file_name: str = TOKEN_FILE,
                      env_name: str = "COPYCAT_API_TOKEN") -> Tuple[str, str]:
    """Returns `(token, where_it_came_from)`. See the module docstring. Also
    resolves the scoped MCP token (`file_name=MCP_TOKEN_FILE`)."""
    if env_token:
        check_token(env_token, source=env_name)
        return env_token, env_name
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / file_name
    try:
        # O_EXCL: two processes starting together never both "win" with
        # different tokens; the loser falls through and reads the file.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = path.read_text(encoding="utf-8").strip()
        check_token(token, source=str(path))
        return token, str(path)
    token = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o600)
    msg = (f"copycat api: {env_name} is empty, generated a token into {path} (mode 0600)."
           + (" Paste its contents into the web UI." if file_name == TOKEN_FILE else
              " The copycat MCP server reads it (scoped: research, theses, plans)."))
    logger.warning(msg)
    print(msg, file=sys.stderr)
    return token, str(path)


def _hosts_from_env() -> List[str]:
    extra = [h.strip() for h in os.environ.get("COPYCAT_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return list(DEFAULT_ALLOWED_HOSTS) + [h for h in extra if h not in DEFAULT_ALLOWED_HOSTS]


@dataclass
class Config:
    data_dir: Path = Path(DEFAULT_DATA_DIR)
    api_token: Optional[str] = None      # None/empty -> resolved from data_dir at create_app()
    bind: str = DEFAULT_BIND
    api_port: int = DEFAULT_API_PORT
    web_origin: str = DEFAULT_WEB_ORIGIN
    sse_poll_s: float = DEFAULT_SSE_POLL_S
    allowed_hosts: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_HOSTS))
    our_address: Optional[str] = None    # COPYCAT_ACCOUNT_ADDRESS: never addable as a leader
    token_source: Optional[str] = None
    mcp_token: Optional[str] = None      # None/empty -> resolved from data_dir/mcp_token
    mcp_token_source: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Config":
        # One absolute data dir for every process: hl's shared rate-bucket
        # file lives there, and the discovery child inherits this env.
        data_dir = Path(os.environ.get("COPYCAT_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
        os.environ["COPYCAT_DATA_DIR"] = str(data_dir)
        return cls(
            data_dir=data_dir,
            api_token=os.environ.get("COPYCAT_API_TOKEN") or None,
            bind=os.environ.get("COPYCAT_BIND", DEFAULT_BIND),
            api_port=int(os.environ.get("COPYCAT_API_PORT", DEFAULT_API_PORT)),
            web_origin=os.environ.get("COPYCAT_WEB_ORIGIN", DEFAULT_WEB_ORIGIN),
            sse_poll_s=float(os.environ.get("COPYCAT_SSE_POLL_S", DEFAULT_SSE_POLL_S)),
            allowed_hosts=_hosts_from_env(),
            our_address=(os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip().lower() or None,
            mcp_token=os.environ.get("COPYCAT_MCP_TOKEN") or None,
        )

    def validate_or_raise(self) -> None:
        """Resolves the token (generating one if needed) and validates it.
        Called once, inside create_app(), so both the real entrypoint and
        every test go through the same gate."""
        token, source = resolve_api_token(self.data_dir, self.api_token)
        self.api_token = token
        self.token_source = source
        mtoken, msource = resolve_api_token(self.data_dir, self.mcp_token, MCP_TOKEN_FILE,
                                            "COPYCAT_MCP_TOKEN")
        if hmac.compare_digest(mtoken, token):
            raise RuntimeError("the MCP token equals the admin api token: the MCP would have full "
                               "access. Delete $COPYCAT_DATA_DIR/mcp_token (or set a different "
                               "COPYCAT_MCP_TOKEN) and restart.")
        self.mcp_token = mtoken
        self.mcp_token_source = msource
