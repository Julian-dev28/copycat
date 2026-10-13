"""Encryption at rest. AES-256-GCM (the `cryptography` library) everywhere.

Two key sources:
  machine  vault/machine.key: 32 random bytes, 0600, created once. Encrypts
           AGENT keys, which the engine must decrypt unattended (no passphrase).
  scrypt   the user's passphrase, n=2**15 r=8 p=1, 16-byte random salt per
           blob. Encrypts MAIN keys of created wallets. Never cached.

Every blob is bound to its owner with GCM associated data (account id, purpose,
address), so a ciphertext copied onto another account fails to decrypt instead
of silently signing for the wrong wallet.

Blob (JSON): {"v": 1, "kdf": "machine"|"scrypt", "salt"?, "n"?, "r"?, "p"?,
"nonce", "ct"} with base64 fields.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import fsio
from .errors import VaultCorrupt, WrongPassphrase

MACHINE_KEY_FILE = "machine.key"
# Audit M7: 2^17 (128 MB, ~0.2 s) for keys that can withdraw. Blobs carry their
# own params, so older 2^15 blobs still open; manage._unlock_main re-seals them
# at these params on the next successful unlock.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1
_MAX_SCRYPT_N = 2 ** 20        # a tampered blob must not make us burn GBs of RAM


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: Any) -> bytes:
    try:
        return base64.b64decode(str(s), validate=True)
    except Exception as exc:
        raise VaultCorrupt("vault blob is not valid base64") from exc


def machine_key() -> bytes:
    path = fsio.vault_dir() / MACHINE_KEY_FILE
    if not path.exists():
        fsio.create_exclusive(path, os.urandom(32))   # loser of a race just reads the winner's
    key = fsio.read_private(path)
    if len(key) != 32:
        raise VaultCorrupt(f"{path} is not a 32-byte key")
    return key


def seal_machine(plaintext: bytes, aad: bytes) -> Dict[str, Any]:
    nonce = os.urandom(12)
    ct = AESGCM(machine_key()).encrypt(nonce, plaintext, aad)
    return {"v": 1, "kdf": "machine", "nonce": _b64(nonce), "ct": _b64(ct)}


def open_machine(blob: Dict[str, Any], aad: bytes) -> bytes:
    if blob.get("v") != 1 or blob.get("kdf") != "machine":
        raise VaultCorrupt("not a machine-key blob")
    try:
        return AESGCM(machine_key()).decrypt(_unb64(blob["nonce"]), _unb64(blob["ct"]), aad)
    except InvalidTag as exc:
        raise VaultCorrupt("agent key failed authentication (machine.key replaced or file moved)") from exc


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def seal_passphrase(plaintext: bytes, passphrase: str, aad: bytes) -> Dict[str, Any]:
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {"v": 1, "kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)}


def open_passphrase(blob: Dict[str, Any], passphrase: str, aad: bytes) -> bytes:
    """Raises WrongPassphrase for ANY authentication failure: a wrong passphrase,
    a different account's blob, a flipped bit. One message, no hint."""
    if blob.get("v") != 1 or blob.get("kdf") != "scrypt":
        raise VaultCorrupt("not a passphrase blob")
    try:
        n, r, p = int(blob["n"]), int(blob["r"]), int(blob["p"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VaultCorrupt("bad scrypt parameters") from exc
    if not (2 <= n <= _MAX_SCRYPT_N and 1 <= r <= 16 and 1 <= p <= 4):
        raise VaultCorrupt("scrypt parameters out of range")
    key = _derive(passphrase, _unb64(blob["salt"]), n, r, p)
    try:
        return AESGCM(key).decrypt(_unb64(blob["nonce"]), _unb64(blob["ct"]), aad)
    except InvalidTag:
        raise WrongPassphrase() from None
