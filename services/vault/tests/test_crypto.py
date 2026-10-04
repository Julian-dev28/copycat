"""Encryption at rest: round trips, AAD binding, wrong passphrase, file modes."""
from __future__ import annotations

import json
import os
import stat

import pytest
from vault import crypto, fsio, store
from vault.errors import VaultCorrupt, WrongPassphrase


def _mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_machine_key_is_created_once_32_bytes_0600_in_a_0700_dir(vault_env):
    k1 = crypto.machine_key()
    k2 = crypto.machine_key()
    path = vault_env / "vault" / "machine.key"
    assert k1 == k2 and len(k1) == 32
    assert _mode(path) == 0o600
    assert _mode(vault_env / "vault") == 0o700


def test_machine_key_race_keeps_the_first_writer(vault_env):
    fsio.ensure_dir(vault_env / "vault")
    assert fsio.create_exclusive(vault_env / "vault" / "machine.key", b"a" * 32) is True
    assert fsio.create_exclusive(vault_env / "vault" / "machine.key", b"b" * 32) is False
    assert crypto.machine_key() == b"a" * 32


def test_machine_round_trip_and_aad_binding():
    blob = crypto.seal_machine(b"secret", b"acct-1")
    assert crypto.open_machine(blob, b"acct-1") == b"secret"
    assert "secret" not in json.dumps(blob)
    with pytest.raises(VaultCorrupt):
        crypto.open_machine(blob, b"acct-2")


def test_passphrase_round_trip_wrong_passphrase_and_wrong_owner():
    blob = crypto.seal_passphrase(b"main-key", "correct horse battery", b"a")
    assert blob["n"] == 2 ** 15 and blob["r"] == 8 and blob["p"] == 1
    assert crypto.open_passphrase(blob, "correct horse battery", b"a") == b"main-key"
    with pytest.raises(WrongPassphrase) as e1:
        crypto.open_passphrase(blob, "wrong horse battery", b"a")
    with pytest.raises(WrongPassphrase) as e2:
        crypto.open_passphrase(blob, "correct horse battery", b"b")
    assert str(e1.value) == str(e2.value) == "invalid passphrase"   # no hint which part was wrong


def test_tampered_scrypt_params_are_refused_before_deriving():
    blob = crypto.seal_passphrase(b"x", "pass phrase 123", b"a")
    blob["n"] = 2 ** 30
    with pytest.raises(VaultCorrupt):
        crypto.open_passphrase(blob, "pass phrase 123", b"a")


def test_secret_files_are_0600_and_hold_no_plaintext(vault_env):
    aid = store.new_id()
    agent_key = "0x" + "ab" * 32
    store.write_agent_key(aid, "0x" + "cd" * 20, agent_key)
    store.write_main_key(aid, "0x" + "ef" * 20, "0x" + "12" * 32, "a long passphrase")
    for p in (vault_env / "vault" / "keys").iterdir():
        assert _mode(p) == 0o600
        body = p.read_text()
        assert "ab" * 32 not in body and "12" * 32 not in body
    assert _mode(vault_env / "vault" / "keys") == 0o700
    assert store.read_agent_key(aid) == agent_key
    assert store.read_main_key(aid, "0x" + "ef" * 20, "a long passphrase") == "0x" + "12" * 32


def test_loosened_file_mode_is_tightened_on_read(vault_env):
    crypto.machine_key()
    path = vault_env / "vault" / "machine.key"
    os.chmod(path, 0o644)
    crypto.machine_key()
    assert _mode(path) == 0o600


def test_atomic_write_leaves_no_temp_files(vault_env):
    target = vault_env / "vault" / "accounts.json"
    for i in range(3):
        fsio.atomic_write(target, f'{{"i": {i}}}'.encode())
    assert json.loads(target.read_text()) == {"i": 2}
    assert [p.name for p in target.parent.iterdir() if p.name.startswith(".tmp")] == []
