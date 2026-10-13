"""Audit M6 (persisted per-account passphrase guard) and M7 (re-seal weak blobs)."""
from __future__ import annotations

import json

import pytest
from vault import crypto, guess_guard, public, store
from vault.errors import WrongPassphrase

PASS = "correct horse battery staple"


def test_lock_schedule():
    assert [guess_guard.lock_seconds(n) for n in (1, 2, 3)] == [0, 0, 0]
    assert guess_guard.lock_seconds(4) == 60 and guess_guard.lock_seconds(5) == 120
    assert guess_guard.lock_seconds(40) == guess_guard.MAX_LOCK_S


def test_wrong_passphrases_lock_every_route_of_that_account_and_persist(fake_hl, vault_env, monkeypatch):
    acct, _, _ = public.create_account("C", PASS)
    for _ in range(guess_guard.FREE_FAILS + 1):
        with pytest.raises(WrongPassphrase):
            public.refresh_agent(acct.id, "wrong passphrase!!")
    tried = []
    real = store.read_main_key
    monkeypatch.setattr(store, "read_main_key", lambda *a: tried.append(1) or real(*a))
    with pytest.raises(guess_guard.TooManyGuesses, match="try again in 1 min"):
        public.refresh_agent(acct.id, PASS)                      # even the right one waits
    assert tried == []                                           # no scrypt while locked: no oracle
    with pytest.raises(guess_guard.TooManyGuesses):
        public.run_user_action(acct.id, "usd_class_transfer", 5, 100.0, PASS, to_perp=True)
    doc = json.loads((vault_env / "vault" / guess_guard.GUARD_FILE).read_text())
    assert doc[acct.id]["fails"] == guess_guard.FREE_FAILS + 1   # on disk: survives a restart
    assert (vault_env / "vault" / guess_guard.GUARD_FILE).stat().st_mode & 0o777 == 0o600


def test_success_clears_the_count(fake_hl, vault_env):
    acct, _, _ = public.create_account("C", PASS)
    with pytest.raises(WrongPassphrase):
        public.refresh_agent(acct.id, "wrong passphrase!!")
    public.refresh_agent(acct.id, PASS)
    assert acct.id not in json.loads((vault_env / "vault" / guess_guard.GUARD_FILE).read_text())


def test_m7_a_weak_blob_is_resealed_at_the_current_params(fake_hl, vault_env, monkeypatch):
    monkeypatch.setattr(crypto, "SCRYPT_N", 2 ** 14)
    acct, _, _ = public.create_account("C", PASS)               # sealed weak, like an old install
    monkeypatch.setattr(crypto, "SCRYPT_N", 2 ** 17)
    assert store.main_key_scrypt_n(acct.id) == 2 ** 14
    public.refresh_agent(acct.id, PASS)
    assert store.main_key_scrypt_n(acct.id) == 2 ** 17
    public.refresh_agent(acct.id, PASS)                         # still opens


def test_l5_agent_key_aad_is_bound_to_the_rows_agent_address(fake_hl, vault_env):
    from eth_account import Account
    from vault.errors import VaultCorrupt
    acct, _, _ = public.create_account("C", PASS)
    row = next(r for r in store.load()["accounts"] if r["id"] == acct.id)
    assert store.read_agent_key(acct.id, row["agent_address"])
    with pytest.raises(VaultCorrupt):
        store.read_agent_key(acct.id, Account.create().address)   # a blob that is not this row's


def test_l6_archive_moves_the_main_key_durably(fake_hl, vault_env, monkeypatch):
    from vault import fsio
    synced = []
    monkeypatch.setattr(fsio, "_fsync_dir", lambda p: synced.append(p.name))
    acct, _, _ = public.create_account("C", PASS)
    store.archive_main_key(acct.id)
    assert synced[-2:] == ["removed", "keys"]
