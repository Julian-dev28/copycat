"""Contract v8 on engine.public: the Trade ticket preview with counter and coin
filters, wallet_ledgers / archive_wallet, and one wallet's event history read
from the tail of events.jsonl."""
from __future__ import annotations

import json

import pytest
from engine import events as events_mod
from engine.state import Copy, EngineState
from engine_fakes import LEADER1, LEADER2, OUR

from contracts.models import EngineEvent, Settings, WalletCopyRequest


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COPYCAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPYCAT_ACCOUNT_ADDRESS", OUR)
    return tmp_path


# ── preview ──────────────────────────────────────────────────────────────────

def test_preview_counter_flips_sides_and_filters_coins(data_dir, venue):
    from engine import public
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)            # $100k long
    venue.hold(LEADER1, "ETH", -1000.0, entry_px=100.0)           # $100k short
    req = WalletCopyRequest(allocation_usd=1000.0, trade_direction="counter",
                            coin_blocklist=["eth"])
    pv = public.preview_wallet(LEADER1, req, Settings(), venue=venue)
    by = {s.coin: s for s in pv.slices}
    assert by["BTC"].side == "short" and by["ETH"].side == "long"
    # match: 100k / 1M x 1000 = $100 for BTC; ETH filtered and NOT handed to BTC
    assert by["BTC"].notional_usd == pytest.approx(100.0)
    assert by["ETH"].status == "skip" and by["ETH"].reason == "filtered: ETH"
    assert pv.copied == 1 and pv.skipped == 1
    assert pv.planned_notional_usd == pytest.approx(100.0)
    assert any("counter" in n for n in pv.notes)


def test_preview_counter_reads_depth_on_our_side(data_dir, venue):
    from engine import public
    sides = []
    orig = venue.depth_usd

    def depth(coin, is_buy, pct):
        sides.append(is_buy)
        return orig(coin, is_buy, pct)
    venue.depth_usd = depth
    venue.hold(LEADER1, "BTC", 1000.0, entry_px=100.0)
    public.preview_wallet(LEADER1, WalletCopyRequest(allocation_usd=100.0, trade_direction="counter"),
                          Settings(), venue=venue)
    assert sides == [False]


def test_wallet_settings_carries_the_v8_fields():
    from engine import public
    req = WalletCopyRequest(allocation_usd=10.0, trade_direction="counter",
                            coin_allowlist=["BTC"], coin_blocklist=["xyz:TSLA"])
    es = public.wallet_settings(Settings(), LEADER1, req)
    assert es.trade_direction.value == "counter"
    assert es.coin_allowlist == ["BTC"] and es.coin_blocklist == ["xyz:TSLA"]


# ── ledger / archive ─────────────────────────────────────────────────────────

def test_archive_wallet_marks_the_ledger_and_refuses_while_copies_exist(data_dir):
    from engine import account as account_mod
    from engine import public
    with EngineState(account_mod.db_path(OUR)) as st:
        st.put_copy(Copy("BTC", LEADER1, 1, 5, False, "allocation"))
    with pytest.raises(public.ArchiveRefused):
        public.archive_wallet(LEADER1, now_ms=10)
    row = public.archive_wallet(LEADER2.upper().replace("0X", "0x"), now_ms=11)
    assert row["archived_ms"] == 11
    led = public.wallet_ledgers()
    assert led[LEADER2]["archived_ms"] == 11 and LEADER1 not in led


def test_wallet_ledgers_is_empty_without_a_db(data_dir):
    from engine import public
    assert public.wallet_ledgers() == {}


# ── one wallet's events ──────────────────────────────────────────────────────

def _write(path, evs):
    with open(path, "w") as fh:
        for e in evs:
            fh.write(e.model_dump_json() + "\n")


def test_read_leader_events_filters_pages_and_reads_across_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(events_mod, "_TAIL_BLOCK", 97)        # many small blocks, lines split across them
    path = tmp_path / "events.jsonl"
    evs = []
    for i in range(30):
        who = LEADER1 if i % 3 == 0 else LEADER2
        action = "skip" if i % 2 else "open"
        evs.append(EngineEvent(ts_ms=1000 + i, action=action, leader=who, coin="BTC",
                               reason="paused" if action == "skip" else None))
    evs.append(EngineEvent(ts_ms=2000, action="halt", reason="no leader"))
    _write(path, evs)
    with open(path, "a") as fh:
        fh.write("not json\n")
    got = events_mod.read_leader_events(path, LEADER1, limit=100)
    assert [e.ts_ms for e in got] == [1027, 1024, 1021, 1018, 1015, 1012, 1009, 1006, 1003, 1000]
    assert any(e.action == "skip" and e.reason == "paused" for e in got)
    page = events_mod.read_leader_events(path, LEADER1, limit=3, before_ms=1018)
    assert [e.ts_ms for e in page] == [1015, 1012, 1009]
    assert events_mod.read_leader_events(path, LEADER1.upper().replace("0X", "0x"), limit=1)[0].ts_ms == 1027


def test_read_leader_events_stops_at_the_scan_cap(tmp_path):
    path = tmp_path / "events.jsonl"
    old = [EngineEvent(ts_ms=i, action="open", leader=LEADER1, coin="BTC") for i in range(5)]
    noise = [EngineEvent(ts_ms=100 + i, action="open", leader=LEADER2, coin="ETH") for i in range(500)]
    _write(path, old + noise)
    size_noise = sum(len(e.model_dump_json()) + 1 for e in noise)
    assert events_mod.read_leader_events(path, LEADER1, max_scan_bytes=size_noise // 2) == []
    assert len(events_mod.read_leader_events(path, LEADER1)) == 5


def test_read_leader_events_missing_file_is_empty(tmp_path):
    assert events_mod.read_leader_events(tmp_path / "nope.jsonl", LEADER1) == []


def test_public_leader_events_reads_the_data_dir_log(data_dir):
    from engine import public
    _write(data_dir / "events.jsonl", [EngineEvent(ts_ms=5, action="skip", leader=LEADER1, coin="X",
                                                   reason="filtered: X")])
    got = public.leader_events(LEADER1, limit=10)
    assert len(got) == 1 and got[0].reason == "filtered: X"
    assert json.loads(got[0].model_dump_json())["leader"] == LEADER1
