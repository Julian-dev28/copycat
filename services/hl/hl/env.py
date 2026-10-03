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
"""
from __future__ import annotations

import os

from hyperliquid.utils import constants

DEFAULT_TIMEOUT_S = 10.0


def network() -> str:
    n = (os.environ.get("COPYCAT_NETWORK") or "mainnet").strip().lower()
    return n if n in ("mainnet", "testnet") else "mainnet"


def base_url() -> str:
    return constants.TESTNET_API_URL if network() == "testnet" else constants.MAINNET_API_URL


def agent_key() -> str:
    return (os.environ.get("COPYCAT_AGENT_KEY") or "").strip()


def account_address() -> str:
    return (os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip()


def has_write_creds() -> bool:
    return bool(agent_key() and account_address())


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
