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
from typing import List, Optional, Tuple

from eth_account import Account
from hyperliquid.exchange import Exchange

from . import env, meta
from .http import set_session_timeout

logger = logging.getLogger(__name__)

_exchange: Optional[Exchange] = None
# (agent address, main account, base url) the cached Exchange was built for.
# get_exchange rebuilds when the active credentials change (vault account switch).
_exchange_key: Optional[Tuple[str, str, str]] = None
_lock = threading.Lock()


def reset() -> None:
    """Test hook: drop the cached Exchange so a changed env/key takes
    effect on the next get_exchange() call."""
    global _exchange, _exchange_key
    with _lock:
        _exchange = None
        _exchange_key = None


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


class MainWalletKeyError(RuntimeError):
    """COPYCAT_AGENT_KEY derives to COPYCAT_ACCOUNT_ADDRESS: the main
    wallet's own private key was pasted. That key can withdraw funds;
    copycat must only ever hold an agent (API) wallet key, which can trade
    but cannot withdraw."""


MAIN_WALLET_KEY_ERROR = (
    "COPYCAT_AGENT_KEY is the private key of COPYCAT_ACCOUNT_ADDRESS itself (your main wallet). "
    "copycat refuses to use it: that key can withdraw your funds. Create an API wallet at "
    "https://app.hyperliquid.xyz/API, authorize it, and put ITS private key in COPYCAT_AGENT_KEY."
)


def check_agent_key(key: str, account: str) -> Optional[str]:
    """None when `key` is a usable agent key for `account`, else the error
    to show the user. Never raises."""
    try:
        derived = Account.from_key(key.removeprefix("0x")).address
    except Exception as exc:
        return f"COPYCAT_AGENT_KEY is not a valid private key: {type(exc).__name__}"
    if derived.lower() == account.strip().lower():
        return MAIN_WALLET_KEY_ERROR
    return None


def _build_exchange(key: str, account: str) -> Exchange:
    """Construct a fully timeout-guarded Exchange. Network-bound: the SDK's
    Exchange.__init__ builds an Info that reads spotMeta, perpDexs and one
    meta per dex right in the constructor. `timeout=` is passed so every
    one of those calls is bounded (the SDK's default None would let a dead
    socket hang the engine forever), and both sessions also get the
    `timeout None -> default` guard for every later call."""
    timeout_s = env.request_timeout_s()
    wallet = Account.from_key(key.removeprefix("0x"))
    ex = Exchange(
        wallet=wallet,
        base_url=env.base_url(),
        account_address=account,
        perp_dexs=_perp_dexs_arg(),
        timeout=timeout_s,
    )
    set_session_timeout(ex, timeout_s)
    info = getattr(ex, "info", None)
    if info is not None:
        set_session_timeout(info, timeout_s)
    return ex


def get_exchange() -> Exchange:
    """The shared Exchange for the active credentials and network.

    Credentials come from `env.credentials()` (vault active account, else
    COPYCAT_ACCOUNT_ADDRESS/COPYCAT_AGENT_KEY), re-resolved on every call. The
    cached Exchange is keyed on (agent address, main account, base url): when
    the user activates another account the next write builds a new one, so an
    order can never be signed for account A while B is active.

    Raises RuntimeError if credentials are missing, and MainWalletKeyError if
    the key is the main wallet's own key. Callers in venue.py check
    `env.has_write_creds()` first and turn any raise here into
    `{ok: False, error}` before anything is sent.

    The lock only guards the singleton slot, never the construction: the
    Exchange constructor does ~13 network reads, and holding a lock across
    them would stall every other writer thread behind a slow HL. Two
    threads racing a cold start may both build one; the first stored for
    the same key wins and the other is dropped, which is harmless.
    """
    global _exchange, _exchange_key
    account, key = env.credentials()
    if not (key and account):
        raise RuntimeError("COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set")
    err = check_agent_key(key, account)
    if err:
        raise MainWalletKeyError(err) if err == MAIN_WALLET_KEY_ERROR else RuntimeError(err)
    cache_key = (Account.from_key(key.removeprefix("0x")).address.lower(), account.lower(), env.base_url())
    ex, ex_key = _exchange, _exchange_key
    if ex is not None and ex_key == cache_key:
        return ex
    if ex is not None:
        logger.info("[hl.sdk] trading credentials changed (account %s, agent %s): rebuilding Exchange",
                    cache_key[1], cache_key[0])
    built = _build_exchange(key, account)
    with _lock:
        if _exchange is None or _exchange_key != cache_key:
            _exchange, _exchange_key = built, cache_key
        return _exchange
