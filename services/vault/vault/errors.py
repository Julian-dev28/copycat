"""Vault errors. Every message is safe to show the user: none ever contains a
key, a passphrase, a ciphertext or a signature. `http_status` is the api's
mapping (services/api/api/routes/accounts.py)."""
from __future__ import annotations


class VaultError(Exception):
    http_status = 400


class InvalidRequest(VaultError):
    http_status = 400


class WrongPassphrase(VaultError):
    """Decryption failed. Deliberately says nothing about why."""
    http_status = 401

    def __init__(self, msg: str = "invalid passphrase") -> None:
        super().__init__(msg)


class MainKeyRefused(InvalidRequest):
    """The pasted key IS the main wallet's key (it can withdraw)."""


class SignatureMismatch(InvalidRequest):
    """The approveAgent signature was not made by the claimed main address."""


class AccountNotFound(VaultError):
    http_status = 404


class Conflict(VaultError):
    http_status = 409


class NeedsFunding(Conflict):
    """HL rejects approveAgent from an address it has never seen (no deposit)."""


class NeedsBrowserSignIn(Conflict):
    """Connected accounts renew their agent through the browser sign-in again."""


class HlRejected(VaultError):
    """Hyperliquid answered, and said no. The message carries HL's own text."""
    http_status = 502


class HlUnavailable(VaultError):
    """A Hyperliquid read or post failed (network, rate budget, bad shape)."""
    http_status = 502


class VaultCorrupt(VaultError):
    """A vault file exists but cannot be parsed or authenticated."""
    http_status = 500


FUND_FIRST = ("Hyperliquid does not know this wallet yet: fund it first (deposit USDC to "
              "{address} on Hyperliquid), then press Refresh agent.")
