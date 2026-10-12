"""Network selection and credentials, read fresh from the environment on
every call (never cached at import time) so a test -- or a future hot-reload
of settings -- can flip COPYCAT_NETWORK / the keys and have it take effect
immediately, with no process restart.

COPYCAT_NETWORK: "mainnet" (default) or "testnet" -- picks the Hyperliquid
base URL for every /info and /exchange call this service makes.
COPYCAT_HL_BASE_URL / COPYCAT_HL_STATS_URL (loopback URLs only) replace both
hosts; the e2e lane (e2e/) points the whole stack at a local mock Hyperliquid.

COPYCAT_AGENT_KEY + COPYCAT_ACCOUNT_ADDRESS gate every write (set_leverage,
market, close). Reads work without them. Per docs/ARCHITECTURE.md: the
agent ("API") wallet signs, the main wallet (COPYCAT_ACCOUNT_ADDRESS) holds
the funds -- this is the SDK's `account_address=main, wallet=agent` split,
never the main wallet's own private key.

Credential resolution (`credentials()`, `account_address()`, `agent_key()`):
  1. the vault (services/vault), once it is authoritative (an account has been
     activated at least once): its ACTIVE account's main address + decrypted
     agent key. From then on no active account (or one without an agent key)
     means no write credentials, never a silent fall back to .env. Creating a
     vault account alone does not change who trades.
  2. otherwise COPYCAT_ACCOUNT_ADDRESS + COPYCAT_AGENT_KEY.
Read on every call (cheap: one small JSON read + one AES-GCM decrypt), so
activating another account takes effect on the next write with no restart.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0


def network() -> str:
    n = (os.environ.get("COPYCAT_NETWORK") or "mainnet").strip().lower()
    return n if n in ("mainnet", "testnet") else "mainnet"


STATS_HOST = "https://stats-data.hyperliquid.xyz"
# COPYCAT_HL_BASE_URL / COPYCAT_HL_STATS_URL only ever point at this machine (the
# e2e lane's mock Hyperliquid). A browser-signed withdraw or usdSend posted to a
# remote override could be replayed on the real chain, so anything else is ignored.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _loopback_override(var: str) -> str:
    """The env override `var` (scheme://loopback-host[:port], no trailing
    slash), or "" when unset or not on this machine (logged, then ignored)."""
    raw = (os.environ.get(var) or "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        ok = parsed.scheme in ("http", "https") and parsed.hostname in _LOOPBACK_HOSTS
    except ValueError:
        ok = False
    if not ok:
        logger.error("[hl.env] %s=%r is not a loopback http(s) URL: ignored, using the real Hyperliquid",
                     var, raw)
        return ""
    return raw


def base_url() -> str:
    """The /info + /exchange base. COPYCAT_HL_BASE_URL (loopback only) wins:
    the e2e lane runs the whole stack against a local mock Hyperliquid."""
    override = _loopback_override("COPYCAT_HL_BASE_URL")
    if override:
        return override
    return constants.TESTNET_API_URL if network() == "testnet" else constants.MAINNET_API_URL


def stats_url() -> str:
    """The stats-data host (leaderboard). COPYCAT_HL_STATS_URL, else
    COPYCAT_HL_BASE_URL (both loopback only), else stats-data.hyperliquid.xyz."""
    return (_loopback_override("COPYCAT_HL_STATS_URL")
            or _loopback_override("COPYCAT_HL_BASE_URL")
            or STATS_HOST)


def vault_exists() -> bool:
    data_dir = Path(os.environ.get("COPYCAT_DATA_DIR") or "./data")
    return (data_dir / "vault" / "accounts.json").exists()


def vault_decides() -> bool:
    """True when the vault, not the env vars, owns the credentials. A vault that
    exists but cannot be loaded decides too (fail closed: no credentials)."""
    if not vault_exists():
        return False
    try:
        return bool(_vault().is_authoritative())
    except Exception as exc:
        logger.error("[hl.env] vault present but unreadable, no write credentials: %s", type(exc).__name__)
        return True


def _vault() -> Any:
    """vault.public, imported lazily (services/vault imports hl, not the reverse
    at module load). Raises if a vault exists but cannot be loaded: callers fail
    closed (no credentials), they never fall back to .env."""
    from vault import public  # type: ignore[import-not-found]
    return public


def credentials() -> Tuple[str, str]:
    """(main account address, agent private key); "" for a missing part."""
    if vault_decides():
        try:
            creds: Optional[Tuple[str, str]] = _vault().active_credentials()
        except Exception as exc:
            logger.error("[hl.env] vault present but unreadable, no write credentials: %s",
                         type(exc).__name__)
            return "", ""
        return (creds[0], creds[1]) if creds else ("", "")
    return ((os.environ.get("COPYCAT_ACCOUNT_ADDRESS") or "").strip(),
            (os.environ.get("COPYCAT_AGENT_KEY") or "").strip())


@dataclass(frozen=True)
class Credentials:
    """Write credentials pinned for one engine cycle (audit B2).

    `pin_credentials()` resolves them ONCE; every write of that cycle passes
    this object back to the venue, which signs with exactly these (never the
    active account re-resolved per call) and refuses the write when the active
    account is no longer `account`. Frozen: nothing can swap the account or the
    key mid-cycle. The key never shows up in repr/logs."""
    account: str                                   # main account, lowercase
    agent_key: str = field(repr=False)


def pin_credentials() -> Optional[Credentials]:
    """The active (account, agent key) as an immutable Credentials, or None when
    either part is missing."""
    account, key = credentials()
    if not (account and key):
        return None
    return Credentials(account.strip().lower(), key)


def account_changed(creds: Credentials) -> Optional[str]:
    """None while `creds.account` is still the active account, else the error a
    pinned write returns instead of sending. Keyless (no decrypt)."""
    active = (account_address() or "").strip().lower()
    if active == creds.account:
        return None
    return (f"active account changed since the cycle started (pinned {creds.account}, "
            f"active {active or 'none'}): write refused")


def agent_key() -> str:
    return credentials()[1]


def account_address() -> str:
    """The active main account. Never decrypts anything (reads are keyless)."""
    if vault_decides():
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
