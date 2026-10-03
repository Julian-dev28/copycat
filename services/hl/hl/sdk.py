"""Lazy Exchange singleton for Hyperliquid writes.

Reads go through our own `http_post` (hl.http) for full control over
timeouts, retries and the rate limiter. Only writes (set_leverage, market
orders) go through the SDK's `Exchange`, because signing -- msgpack
encoding, ECDSA secp256k1 over the Agent typed-data domain, EIP-712 typed
data for the Exchange domain -- is exactly what the SDK exists for; this
package does not re-implement it.
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional

from eth_account import Account
from hyperliquid.exchange import Exchange

from . import env, meta
from .http import set_session_timeout

logger = logging.getLogger(__name__)

_exchange: Optional[Exchange] = None
_lock = threading.Lock()


def reset() -> None:
    """Test hook: drop the cached Exchange so a changed env/key takes
    effect on the next get_exchange() call."""
    global _exchange
    with _lock:
        _exchange = None


def _perp_dexs_arg() -> Optional[List[str]]:
    """[""] + every HIP-3 dex, so the SDK can resolve `xyz:COIN`-style
    names when signing an order. `""` is the sentinel for the main dex --
    the SDK treats `perp_dexs` as EXCLUSIVE, so passing a list without it
    would drop the main perp universe entirely. None (the SDK's own
    default: main dex only) if dex discovery itself fails -- a down
    dex-list read must not block native-coin orders."""
    try:
        dexes = meta.perp_dexs()
        return [""] + dexes if dexes else None
    except Exception as exc:
        logger.warning(f"[hl.sdk] perp dex discovery failed, HIP-3 coins unresolvable this call: {exc}")
        return None


def get_exchange() -> Exchange:
    """The shared Exchange singleton for the active network.

    Raises RuntimeError if COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS are
    unset. Callers in venue.py check `env.has_write_creds()` BEFORE calling
    this and turn a missing key into `{ok: False, error}` -- this function
    raising is a second line of defense, not the primary contract path.
    """
    global _exchange
    if _exchange is not None:
        return _exchange
    with _lock:
        if _exchange is not None:
            return _exchange
        key = env.agent_key()
        account = env.account_address()
        if not (key and account):
            raise RuntimeError("COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set")
        key_hex = key.removeprefix("0x")
        wallet = Account.from_key(key_hex)
        _exchange = set_session_timeout(Exchange(
            wallet=wallet,
            base_url=env.base_url(),
            account_address=account,
            perp_dexs=_perp_dexs_arg(),
        ))
        return _exchange
