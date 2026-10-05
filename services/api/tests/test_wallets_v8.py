"""Contract v8 Trade page routes: copy with direction/coin lists, pause/resume,
status mapping, archive, one wallet's events, projection (200/202)."""
from __future__ import annotations

from api.settings_store import clean_coins, settings_source
from api.wallet_stop import request_stop
from api_fakes import ADDR_A, ADDR_BUILDING, FakeEngineClient, FakeScoutClient

from contracts.models import (
    EngineEvent,
    EngineStatus,
    LeaderOverride,
    LeaderStatus,
    Settings,
    TradingStyle,
)

A = ADDR_A                      # on the fake Scout board
B = "0x" + "b" * 40
C = "0x" + "d" * 40


def copy(client, headers, addr=A, **body):
    body.setdefault("allocation_usd", 1000.0)
    return client.post(f"/api/wallets/{addr}/copy", headers=headers, json=body)


def rows(client, headers, **params):
    r = client.get("/api/wallets", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {w["address"]: w for w in r.json()}


def status(fake_engine: FakeEngineClient, *leaders: LeaderStatus) -> None:
    fake_engine._status = EngineStatus(running=True, enabled=True, dry_run=False, leaders=list(leaders))


# ── copy with v8 fields ──────────────────────────────────────────────────────

def test_copy_writes_direction_and_cleaned_coin_lists(client, auth_headers):
    r = copy(client, auth_headers, trade_direction="counter",
             coin_allowlist=[" BTC", "btc", "xyz:TSLA", ""], coin_blocklist=["DOGE"])
    assert r.status_code == 200, r.text
    o = r.json()["leader_overrides"][A]
    assert o["trade_direction"] == "counter"
    assert o["coin_allowlist"] == ["BTC", "xyz:TSLA"] and o["coin_blocklist"] == ["DOGE"]


def test_repost_without_lists_keeps_them_and_empty_list_clears_them(client, auth_headers):
    copy(client, auth_headers, coin_blocklist=["DOGE"])
    o = copy(client, auth_headers, allocation_usd=2000.0).json()["leader_overrides"][A]
    assert o["coin_blocklist"] == ["DOGE"]
    o = copy(client, auth_headers, coin_blocklist=[]).json()["leader_overrides"][A]
    assert o["coin_blocklist"] == []


def test_clean_coins():
    assert clean_coins(["eth", "ETH ", " ", "xyz:TSLA"]) == ["eth", "xyz:TSLA"]


# ── pause / resume ───────────────────────────────────────────────────────────

def test_pause_a_global_wallet_writes_a_minimal_override_and_stays_global(client, auth_headers):
    copy(client, auth_headers, settings_source="global")
    r = client.post(f"/api/wallets/{A}/pause", headers=auth_headers)
    assert r.status_code == 200, r.text
    o = r.json()["leader_overrides"][A]
    assert o["paused"] is True
    assert {k for k, v in o.items() if v is not None} == {"paused", "invested_ms"}
    w = rows(client, auth_headers)[A]
    assert w["status"] == "paused" and w["settings_source"] == "global"
    r = client.post(f"/api/wallets/{A}/resume", headers=auth_headers)
    assert r.json()["leader_overrides"][A]["paused"] is None
    assert rows(client, auth_headers)[A]["status"] == "running"


def test_pause_a_wallet_with_no_override_at_all(client, auth_headers):
    client.post("/api/leaders", headers=auth_headers, json={"address": B})
    s = client.post(f"/api/wallets/{B}/pause", headers=auth_headers).json()
    assert s["leader_overrides"][B]["paused"] is True
    s = client.post(f"/api/wallets/{B}/resume", headers=auth_headers).json()
    assert B not in s["leader_overrides"]                  # nothing left: no override


def test_resume_under_a_book_wide_pause_writes_false(client, auth_headers):
    copy(client, auth_headers)
    client.patch("/api/settings", headers=auth_headers, json={"paused": True})
    assert rows(client, auth_headers)[A]["status"] == "paused"
    s = client.post(f"/api/wallets/{A}/resume", headers=auth_headers).json()
    assert s["leader_overrides"][A]["paused"] is False
    assert rows(client, auth_headers)[A]["status"] == "running"


def test_repost_keeps_a_paused_wallet_paused(client, auth_headers):
    copy(client, auth_headers)
    client.post(f"/api/wallets/{A}/pause", headers=auth_headers)
    assert copy(client, auth_headers, allocation_usd=50.0).json()["leader_overrides"][A]["paused"] is True
    o = copy(client, auth_headers, settings_source="global").json()["leader_overrides"][A]
    assert o["paused"] is True


def test_pause_unknown_wallet_is_404(client, auth_headers):
    assert client.post(f"/api/wallets/{B}/pause", headers=auth_headers).status_code == 404
    assert client.post("/api/wallets/nope/pause", headers=auth_headers).status_code == 400


def test_settings_source_ignores_invested_ms_and_paused():
    assert settings_source(LeaderOverride(invested_ms=1, paused=True)) == "global"
    assert settings_source(LeaderOverride(paused=False)) == "global"
    assert settings_source(LeaderOverride(paused=True, trade_direction="counter")) == "custom"


# ── status mapping and the list ──────────────────────────────────────────────

def test_status_mapping_running_paused_stopping_stopped_archived(client, auth_headers, fake_engine,
                                                                 config):
    copy(client, auth_headers, trade_direction="counter", coin_allowlist=["BTC"])
    client.post("/api/leaders", headers=auth_headers, json={"address": B})
    client.post(f"/api/wallets/{B}/pause", headers=auth_headers)
    stopping, stopped, archived = "0x" + "e" * 40, "0x" + "f" * 40, "0x" + "9" * 40
    request_stop(config.data_dir, stopping, True, 1)
    status(fake_engine,
           LeaderStatus(address=stopping, read_ok=True, effective=Settings(), open_copies=1,
                        owned_coins=["ETH"]),
           LeaderStatus(address=stopped, read_ok=True, effective=Settings(), open_copies=1,
                        owned_coins=["SOL"]))
    fake_engine.ledgers = {
        archived: {"leader": archived, "invested_ms": 5, "realized_pnl_usd": 12.5, "fees_usd": 0.5,
                   "terms": {"sizing_mode": "allocation", "allocation_usd": 300.0,
                             "trade_direction": "counter", "invested_ms": 5},
                   "updated_ms": 6, "archived_ms": 7}}
    w = rows(client, auth_headers)
    assert w[A]["status"] == "running" and w[A]["trade_direction"] == "counter"
    assert w[A]["coin_allowlist"] == ["BTC"]
    assert w[B]["status"] == "paused"
    assert w[stopping]["status"] == "stopping"
    assert w[stopped]["status"] == "stopped" and w[stopped]["in_book"] is False
    assert archived not in w
    w = rows(client, auth_headers, include="archived")
    a = w[archived]
    assert (a["status"], a["archived_ms"], a["realized_pnl_usd"], a["allocation_usd"],
            a["trade_direction"], a["settings_source"]) == ("archived", 7, 12.5, 300.0, "counter", "custom")
    assert w[A]["archived_ms"] is None


def test_stopped_wallet_with_history_is_listed_until_archived(client, auth_headers, fake_engine):
    status(fake_engine, LeaderStatus(address=B, read_ok=True, effective=Settings(),
                                     realized_pnl_usd=-3.0))
    fake_engine.ledgers = {B: {"realized_pnl_usd": -3.0, "fees_usd": 0.1, "terms": {},
                               "archived_ms": None}}
    w = rows(client, auth_headers)
    assert w[B]["status"] == "stopped" and w[B]["realized_pnl_usd"] == -3.0
    r = client.post(f"/api/wallets/{B}/archive", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived" and r.json()["archived_ms"]
    assert B not in rows(client, auth_headers)
    assert rows(client, auth_headers, include="archived")[B]["status"] == "archived"


def test_orphan_without_copies_or_history_is_not_listed(client, auth_headers, fake_engine):
    status(fake_engine, LeaderStatus(address=B, read_ok=True, effective=Settings()))
    assert B not in rows(client, auth_headers)


def test_include_rejects_other_values(client, auth_headers):
    r = client.get("/api/wallets", headers=auth_headers, params={"include": "all"})
    assert r.status_code == 422


def test_style_comes_from_the_scout_board_row(client, auth_headers, fake_scout: FakeScoutClient):
    copy(client, auth_headers)                    # A is on the fake board
    copy(client, auth_headers, addr=C)            # C is not (the fake returns A and B for any query)
    orig = fake_scout.page

    def page(query):
        p = orig(query)
        for r in p.rows:
            r.style = TradingStyle.algo
        return p
    fake_scout.page = page
    w = rows(client, auth_headers)
    assert w[A]["style"] == "algo" and w[C]["style"] is None
    assert {"q": A, "limit": 1} in fake_scout.queries


def test_list_survives_scout_failures(client, auth_headers, fake_scout):
    copy(client, auth_headers)

    def boom(query):
        raise RuntimeError("scout down")
    fake_scout.page = boom
    assert rows(client, auth_headers)[A]["style"] is None


# ── archive rules ────────────────────────────────────────────────────────────

def test_archive_refuses_a_wallet_in_the_book(client, auth_headers):
    copy(client, auth_headers)
    r = client.post(f"/api/wallets/{A}/archive", headers=auth_headers)
    assert r.status_code == 409 and "stop it first" in r.json()["detail"]


def test_archive_refuses_while_stopping_or_holding_copies(client, auth_headers, fake_engine, config):
    request_stop(config.data_dir, B, True, 1)
    assert client.post(f"/api/wallets/{B}/archive", headers=auth_headers).status_code == 409
    status(fake_engine, LeaderStatus(address=C, read_ok=True, effective=Settings(), open_copies=1,
                                     owned_coins=["BTC"]))
    r = client.post(f"/api/wallets/{C}/archive", headers=auth_headers)
    assert r.status_code == 409 and "BTC" in r.json()["detail"]


def test_archive_maps_the_engine_refusal_to_409(client, auth_headers, fake_engine):
    fake_engine.archive_refused = "still has copies: ETH"
    r = client.post(f"/api/wallets/{C}/archive", headers=auth_headers)
    assert r.status_code == 409 and "ETH" in r.json()["detail"]


def test_copying_an_archived_wallet_again_shows_it_running(client, auth_headers, fake_engine):
    fake_engine.ledgers = {A: {"realized_pnl_usd": 1.0, "terms": {}, "archived_ms": 5}}
    copy(client, auth_headers)
    assert rows(client, auth_headers)[A]["status"] == "running"


# ── events ───────────────────────────────────────────────────────────────────

def test_wallet_events_filters_by_leader_newest_first_and_pages(client, auth_headers, fake_engine):
    fake_engine.event_log = [
        EngineEvent(ts_ms=1, action="open", leader=A, coin="BTC", side="short"),
        EngineEvent(ts_ms=2, action="skip", leader=B, coin="ETH", reason="paused"),
        EngineEvent(ts_ms=3, action="skip", leader=A, coin="SOL", reason="filtered: SOL"),
        EngineEvent(ts_ms=4, action="close", leader=A, coin="BTC"),
    ]
    r = client.get(f"/api/wallets/{A}/events", headers=auth_headers)
    assert r.status_code == 200
    assert [(e["ts_ms"], e["action"]) for e in r.json()] == [(4, "close"), (3, "skip"), (1, "open")]
    assert r.json()[1]["reason"] == "filtered: SOL"
    r = client.get(f"/api/wallets/{A}/events", headers=auth_headers,
                   params={"before_ms": 4, "limit": 1})
    assert [e["ts_ms"] for e in r.json()] == [3]
    assert client.get(f"/api/wallets/{A}/events", headers=auth_headers,
                      params={"limit": 0}).status_code == 422


def test_wallet_events_503_without_engine(client, auth_headers, app):
    from api.deps import get_engine_client
    from api_fakes import UnavailableEngineClient

    class NoEvents(UnavailableEngineClient):
        def leader_events(self, *a, **k):
            from api.engine_client import EngineUnavailable
            raise EngineUnavailable("boom")
    app.dependency_overrides[get_engine_client] = lambda: NoEvents()
    assert client.get(f"/api/wallets/{A}/events", headers=auth_headers).status_code == 503


# ── projection ───────────────────────────────────────────────────────────────

def test_projection_200_uses_the_query_terms(client, auth_headers, fake_scout):
    copy(client, auth_headers, coin_blocklist=["DOGE"])
    r = client.get(f"/api/wallets/{A}/projection", headers=auth_headers,
                   params={"allocation_usd": 500, "trade_direction": "counter",
                           "exposure_mode": "target", "target_leverage": 3})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["allocation_usd"] == 500.0 and p["trade_direction"] == "counter"
    assert p["return_pct"] == 3.0 and p["copies"] == 20 and "counter" in p["note"]
    addr, settings, equity, ov = fake_scout.what_if_calls[-1]
    assert addr == A and equity == 500.0
    assert (ov.sizing_mode.value, ov.allocation_usd, ov.trade_direction.value, ov.exposure_mode.value,
            ov.target_leverage) == ("allocation", 500.0, "counter", "target", 3)
    assert settings.for_leader(A).coin_blocklist == ["DOGE"]     # his filters ride along


def test_projection_defaults_to_the_wallets_direction(client, auth_headers, fake_scout):
    copy(client, auth_headers, trade_direction="counter")
    r = client.get(f"/api/wallets/{A}/projection", headers=auth_headers)
    assert r.status_code == 200 and r.json()["trade_direction"] == "counter"
    assert r.json()["allocation_usd"] == 1000.0


def test_projection_202_queues_a_build_when_nothing_is_cached(client, auth_headers, fake_scout):
    fake_scout.what_if_missing = {ADDR_BUILDING}
    r = client.get(f"/api/wallets/{ADDR_BUILDING}/projection", headers=auth_headers)
    assert r.status_code == 202 and r.json()["state"] == "running"


def test_projection_404_when_scout_has_nothing_and_cannot_build(client, auth_headers, fake_scout):
    fake_scout.what_if_missing = {C}                 # profile() answers None for C
    assert client.get(f"/api/wallets/{C}/projection", headers=auth_headers).status_code == 404


def test_projection_409_while_a_what_if_runs(client, auth_headers, fake_scout):
    fake_scout.what_if_busy = True
    assert client.get(f"/api/wallets/{A}/projection", headers=auth_headers).status_code == 409


def test_projection_rejects_bad_terms(client, auth_headers):
    assert client.get(f"/api/wallets/{A}/projection", headers=auth_headers,
                      params={"allocation_usd": 0}).status_code == 422
    assert client.get(f"/api/wallets/{A}/projection", headers=auth_headers,
                      params={"trade_direction": "sideways"}).status_code == 422
