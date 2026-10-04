"""The .env credentials for POST /api/accounts/import-env (migration to the vault).

create_app() pops COPYCAT_AGENT_KEY from the api's environment, so the key is
read from the env file at request time and handed straight to the vault:
  COPYCAT_ENV_FILE if set (docker compose mounts the host .env there, read-only),
  else ./.env unless COPYCAT_SKIP_DOTENV=1.
The process env wins when it still has a value (e.g. a test).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def _env_file() -> Optional[Path]:
    explicit = os.environ.get("COPYCAT_ENV_FILE")
    if explicit:
        return Path(explicit)
    if os.environ.get("COPYCAT_SKIP_DOTENV") == "1":
        return None
    return Path(".env")


def env_credentials() -> Tuple[Optional[str], Optional[str]]:
    """(COPYCAT_ACCOUNT_ADDRESS, COPYCAT_AGENT_KEY), None for a missing part."""
    address = (os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip() or None
    key = (os.environ.get("COPYCAT_AGENT_KEY") or "").strip() or None
    path = _env_file()
    if (address is None or key is None) and path is not None and path.is_file():
        from dotenv import dotenv_values
        values = dotenv_values(path)
        address = address or (values.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip() or None
        key = key or (values.get("COPYCAT_AGENT_KEY") or "").strip() or None
    if address in ("0x...",):
        address = None
    if key in ("0x...",):
        key = None
    return address, key
