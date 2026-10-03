"""EngineState: SQLite persistence across a simulated restart (new
EngineState instance pointed at the same file). WAL mode is implicit --
if it were off this would still pass locally, but it is what makes a
second process able to read while the engine process writes."""
from __future__ import annotations

from engine.state import Copy, DryCopy, EngineState, LeaderState


def test_leader_state_persists_across_restart(tmp_path):
    db = tmp_path / "e.db"
    with EngineState(db) as s:
        s.put_leader(LeaderState("0xabc", {"BTC": 1.5}, ["ETH"], 1000))

    with EngineState(db) as s2:
        ls = s2.get_leader("0xabc")
        assert ls is not None
        assert ls.last_positions == {"BTC": 1.5}
        assert ls.ignored == ["ETH"]
        assert ls.last_read_ms == 1000


def test_unknown_leader_returns_none(tmp_path):
    with EngineState(tmp_path / "e.db") as s:
        assert s.get_leader("0xnope") is None


def test_copy_crud_and_persistence_across_restart(tmp_path):
    db = tmp_path / "e.db"
    with EngineState(db) as s:
        s.put_copy(Copy("BTC", "0xabc", 1000, 20, False, "fixed_margin"))
        s.put_copy(Copy("ETH", "0xdef", 2000, 10, True, "proportional"))

    with EngineState(db) as s2:
        c = s2.get_copy("BTC")
        assert c.leader == "0xabc" and c.leverage == 20 and c.is_cross is False
        assert {c.coin for c in s2.all_copies()} == {"BTC", "ETH"}
        s2.delete_copy("BTC")
        assert s2.get_copy("BTC") is None
        assert {c.coin for c in s2.all_copies()} == {"ETH"}


def test_put_copy_upserts_in_place(tmp_path):
    with EngineState(tmp_path / "e.db") as s:
        s.put_copy(Copy("BTC", "0xabc", 1000, 20, False, "fixed_margin"))
        s.put_copy(Copy("BTC", "0xabc", 1000, 40, False, "fixed_margin"))
        assert len(s.all_copies()) == 1
        assert s.get_copy("BTC").leverage == 40


def test_dry_copy_tracks_a_simulated_size_and_persists(tmp_path):
    db = tmp_path / "e.db"
    with EngineState(db) as s:
        s.put_dry_copy(DryCopy("BTC", "0xabc", 1000, 20, False, "fixed_margin", 0.5))

    with EngineState(db) as s2:
        dc = s2.get_dry_copy("BTC")
        assert dc.size == 0.5
        dc.size += 0.25
        s2.put_dry_copy(dc)
        assert s2.get_dry_copy("BTC").size == 0.75
        assert s2.get_copy("BTC") is None            # dry_copies and copies are fully separate tables


def test_kv_roundtrips_arbitrary_json_and_persists(tmp_path):
    db = tmp_path / "e.db"
    with EngineState(db) as s:
        s.set_kv("day_anchor", {"day": "2026-10-02", "equity_usd": 1234.5})
        s.set_kv("halted", True)

    with EngineState(db) as s2:
        assert s2.get_kv("day_anchor") == {"day": "2026-10-02", "equity_usd": 1234.5}
        assert s2.get_kv("halted") is True
        assert s2.get_kv("does_not_exist") is None


def test_leader_addresses_lists_every_known_leader(tmp_path):
    with EngineState(tmp_path / "e.db") as s:
        s.put_leader(LeaderState("0xaaa", {}, [], None))
        s.put_leader(LeaderState("0xbbb", {}, [], None))
        assert set(s.leader_addresses()) == {"0xaaa", "0xbbb"}
