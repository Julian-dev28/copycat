"""Proves SettingsStore.patch() serializes concurrent read-modify-writes via
its flock, so two PATCHes racing on the same file don't lose one's update.

Thread A starts a patch and we hold it mid-critical-section (after it has
acquired the lock, before it writes) via a deliberate pause wrapped around
_write_atomic. Thread B's patch() call then genuinely blocks on the
OS-level flock for that whole window -- flock is a real blocking syscall,
not GIL-visible, so this isn't a timing coincidence -- and only proceeds
once A releases the lock, at which point B's load() sees A's write and
merges on top of it. Without the lock, B could read the pre-A state and
its write would clobber A's change; with it, both land.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from api.settings_store import SettingsStore

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def test_concurrent_patches_do_not_lose_writes(
    client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_write = SettingsStore._write_atomic
    a_holding = threading.Event()
    release_a = threading.Event()
    first_call_done = threading.Event()

    def slow_write(self, settings):
        if not first_call_done.is_set():
            first_call_done.set()
            a_holding.set()
            assert release_a.wait(timeout=2.0), "test deadlocked waiting for release"
        return original_write(self, settings)

    monkeypatch.setattr(SettingsStore, "_write_atomic", slow_write)

    results = {}

    def patch_a():
        results["a"] = client.patch(
            "/api/settings",
            headers=auth_headers,
            json={"leader_overrides": {ADDR_A: {"leverage": 5}}},
        )

    def patch_b():
        results["b"] = client.patch(
            "/api/settings",
            headers=auth_headers,
            json={"leader_overrides": {ADDR_B: {"leverage": 6}}},
        )

    t_a = threading.Thread(target=patch_a)
    t_a.start()
    assert a_holding.wait(timeout=2.0), "A never reached its critical section"

    t_b = threading.Thread(target=patch_b)
    t_b.start()

    release_a.set()
    t_a.join(timeout=2.0)
    t_b.join(timeout=2.0)
    assert not t_a.is_alive() and not t_b.is_alive()

    assert results["a"].status_code == 200
    assert results["b"].status_code == 200

    final = client.get("/api/settings", headers=auth_headers).json()
    overrides = final["leader_overrides"]
    assert ADDR_A in overrides and overrides[ADDR_A]["leverage"] == 5
    assert ADDR_B in overrides and overrides[ADDR_B]["leverage"] == 6
