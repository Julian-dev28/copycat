"""The engine re-resolves its account every cycle and keeps state per account:
copies opened under A are never managed while B is active."""
from __future__ import annotations

import json
import sqlite3

import pytest
from engine import public
from engine.events import read_events
from engine.state import EngineState
from engine_fakes import LEADER1, FakeVenue
from test_core import cfg

A = "0x" + "a" * 40
B = "0x" + "b" * 40


@pytest.fixture
def ddir(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COPYCAT_ACCOUNT_ADDRESS", raising=False)
    (tmp_path / "settings.json").write_text(cfg(leaders=[LEADER1]).model_dump_json())
    return tmp_path


def _vault(ddir, active, authoritative=True):
    """A vault accounts.json as vault.store writes it (addresses only, no keys)."""
    v = ddir / "vault"
    v.mkdir(mode=0o700, exist_ok=True)
    rows = [{"id": f"acc_{c * 16}", "label": c, "kind": "connected_key", "address": addr,
             "agent_status": "active", "created_ms": 1, "has_main_key": False}
            for c, addr in (("a", A), ("b", B))]
    active_id = {A: "acc_" + "a" * 16, B: "acc_" + "b" * 16}.get(active)
    (v / "accounts.json").write_text(json.dumps(
        {"version": 1, "active_id": active_id, "authoritative": authoritative, "accounts": rows}))


def _venue():
    v = FakeVenue()
    v.set_account(A, 1_000_000.0)
    v.set_account(B, 1_000_000.0)
    v.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    return v


def test_switching_accounts_moves_to_a_separate_book_and_logs_it(ddir):
    venue = _venue()
    _vault(ddir, A)
    public.run_cycle(venue, now_ms=1)
    venue.hold(A, "BTC", 0.5, entry_px=100.0)
    with EngineState(public._db_path(A)) as st:
        assert [c.coin for c in st.all_copies()] == ["BTC"]
    assert public.status().our_address == A

    _vault(ddir, B)
    venue.hold(LEADER1, "BTC", 0.0)          # he exits: under B, A's copy must NOT be closed
    public.run_cycle(venue, now_ms=2)
    assert venue.closes == []
    with EngineState(public._db_path(A)) as st:
        assert [c.coin for c in st.all_copies()] == ["BTC"]
    with EngineState(public._db_path(B)) as st:
        assert st.all_copies() == []
    assert public.status().our_address == B
    assert public.status(A).our_address == A and public.status(A).running is False
    evs = read_events(ddir / "events.jsonl", limit=50)
    switch_ev = [e for e in evs if e.reason and "active trading account changed" in e.reason]
    assert switch_ev and A in switch_ev[0].reason and B in switch_ev[0].reason
    assert "1 copies of" in switch_ev[0].reason and switch_ev[0].action == "error"


def test_vault_not_authoritative_keeps_the_env_account(ddir, monkeypatch):
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", A)
    _vault(ddir, None, authoritative=False)
    public.run_cycle(_venue(), now_ms=1)
    assert public.status().our_address == A


def test_no_active_account_idles_without_reading_or_trading(ddir, monkeypatch):
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", A)      # ignored: the vault decides
    _vault(ddir, None)
    venue = _venue()
    calls = []
    real = venue.account_state
    venue.account_state = lambda u: calls.append(u) or real(u)
    out = public.run_cycle(venue, now_ms=1)
    assert calls == [] and venue.orders == [] and out["skipped"] == {"all": "no active trading account"}
    st = public.status()
    assert st.our_address is None and st.halted_reason == "no active trading account"


def test_legacy_engine_db_is_adopted_by_its_owner_only(ddir, monkeypatch):
    with EngineState(ddir / "engine.db") as st:
        st.set_kv("last_status", {"status": {"our_address": A}, "poll_interval_s": 5})
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", B)
    public.run_cycle(_venue(), now_ms=1)
    assert (ddir / "engine.db").exists()                  # B is not its owner
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", A)
    public.run_cycle(_venue(), now_ms=2)
    assert not (ddir / "engine.db").exists() and public._db_path(A).exists()
    conn = sqlite3.connect(public._db_path(A))
    assert conn.execute("SELECT count(*) FROM kv").fetchone()[0] > 0
    conn.close()
