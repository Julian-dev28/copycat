"""Network selection and credentials, read fresh from the environment on
every call (never cached at import time) so a test -- or a future hot-reload
of settings -- can flip COPYCAT_NETWORK / the keys and have it take effect
immediately, with no process restart.

COPYCAT_NETWORK: "mainnet" (default) or "testnet" -- picks the Hyperliquid
base URL for every /info and /exchange call this service makes.

COPYCAT_AGENT_KEY + COPYCAT_ACCOUNT_ADDRESS gate every write (set_leverage,
market, close). Reads work without them. Per docs/ARCHITECTURE.md: the
agent ("API") wallet signs, the main wallet (COPYCAT_ACCOUNT_ADDRESS) holds
the funds -- this is the SDK's `account_address=main, wallet=agent` split,
never the main wallet's own private key.

Credential resolution (`credentials()`, `account_address()`, `agent_key()`):
  1. the vault (services/vault), when `$COPYCAT_DATA_DIR/vault/accounts.json`
     exists: its ACTIVE account's main address + decrypted agent key. Once a
     vault exists it is authoritative: no active account (or one without an
     agent key) means no write credentials, never a silent fall back to .env.
  2. otherwise COPYCAT_ACCOUNT_ADDRESS + COPYCAT_AGENT_KEY.
Read on every call (cheap: one small JSON read + one AES-GCM decrypt), so
activating another account takes effect on the next write with no restart.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional, Tuple

from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0


def network() -> str:
    n = (os.environ.get("COPYCAT_NETWORK") or "mainnet").strip().lower()
    return n if n in ("mainnet", "testnet") else "mainnet"


def base_url() -> str:
    return constants.TESTNET_API_URL if network() == "testnet" else constants.MAINNET_API_URL


def vault_exists() -> bool:
    data_dir = Path(os.environ.get("COPYCAT_DATA_DIR") or "./data")
    return (data_dir / "vault" / "accounts.json").exists()


def _vault() -> Any:
    """vault.public, imported lazily (services/vault imports hl, not the reverse
    at module load). Raises if a vault exists but cannot be loaded: callers fail
    closed (no credentials), they never fall back to .env."""
    from vault import public  # type: ignore[import-not-found]
    return public


def credentials() -> Tuple[str, str]:
    """(main account address, agent private key); "" for a missing part."""
    if vault_exists():
        try:
            creds: Optional[Tuple[str, str]] = _vault().active_credentials()
        except Exception as exc:
            logger.error("[hl.env] vault present but unreadable, no write credentials: %s",
                         type(exc).__name__)
            return "", ""
        return (creds[0], creds[1]) if creds else ("", "")
    return ((os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip(),
            (os.environ.get("COPYCAT_AGENT_KEY") or "").strip())


def agent_key() -> str:
    return credentials()[1]


def account_address() -> str:
    """The active main account. Never decrypts anything (reads are keyless)."""
    if vault_exists():
        try:
            return _vault().active_address() or ""
        except Exception as exc:
            logger.error("[hl.env] vault present but unreadable: %s", type(exc).__name__)
            return ""
    return (os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip()


def has_write_creds() -> bool:
    account, key = credentials()
    return bool(account and key)


def request_timeout_s() -> float:
    try:
        return float(os.environ.get("COPYCAT_HL_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


DEFAULT_CLOSE_MAX_SLIPPAGE_PCT = 1.0


def close_max_slippage_pct() -> float:
    """Slippage cap for close() (the contract's close() has no slippage
    arg). Default 1.0, matching market()'s default. Tunable via
    COPYCAT_HL_CLOSE_SLIPPAGE_PCT for thin books where exits keep hitting
    the cap."""
    try:
        v = float(os.environ.get("COPYCAT_HL_CLOSE_SLIPPAGE_PCT", DEFAULT_CLOSE_MAX_SLIPPAGE_PCT))
        return v if v > 0 else DEFAULT_CLOSE_MAX_SLIPPAGE_PCT
    except (TypeError, ValueError):
        return DEFAULT_CLOSE_MAX_SLIPPAGE_PCT
