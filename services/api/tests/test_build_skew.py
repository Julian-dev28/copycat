"""Audit M12: GET /api/health names the processes running other code than the api."""
from __future__ import annotations

from types import SimpleNamespace

from api import build_skew
from api.schemas import ComponentBuild


def c(name, build="abc", cv=12, alive=True):
    return ComponentBuild(component=name, build=build, contract_version=cv, alive=alive)


def test_same_build_everywhere_is_not_stale():
    assert build_skew.stale(c("api"), [c("engine"), c("scout")]) == []


def test_other_build_unknown_build_or_contract_is_stale_only_when_running():
    api = c("api")
    others = [c("engine", build="old"), c("scout", build=None), c("x", cv=11),
              c("y", build="old", alive=False)]
    assert build_skew.stale(api, others) == ["engine", "scout", "x"]


def test_api_itself_is_stale_when_the_checkout_moved_on():
    api = c("api", build="old0")
    assert build_skew.stale(api, [c("engine", build="old0")], checkout_build="new1") == ["api", "engine"]
    assert build_skew.stale(api, [c("engine", build="old0")], checkout_build="old0") == []
    assert build_skew.stale(api, [], checkout_build="unknown") == []      # no git: never a false alarm
    assert build_skew.stale(api, [], checkout_build=None) == []


def test_health_reports_builds_and_stale(client, app, monkeypatch):
    app.state.build = {"build": "new1", "contract_version": 12, "started_ms": 1}
    eng_public = SimpleNamespace(process_build=lambda: {"build": "old0", "contract_version": 12,
                                                       "started_ms": 0, "alive": True})
    app.state.engine_client_factory = lambda: SimpleNamespace(_public=lambda: eng_public)
    scout_public = SimpleNamespace(scout_build=lambda: {"build": "new1", "contract_version": 12,
                                                        "started_ms": 2, "alive": True})
    app.state.scout_client_factory = lambda: SimpleNamespace(_public=lambda: scout_public)
    from contracts import build as build_mod
    monkeypatch.setattr(build_mod, "checkout_build_id", lambda: "new1")
    body = client.get("/api/health").json()
    assert body["stale"] == ["engine"] and body["checkout_build"] == "new1"
    assert [b["component"] for b in body["builds"]] == ["api", "engine", "scout"]


def test_health_never_fails_when_probes_raise(client, app):
    def boom():
        raise RuntimeError("down")
    app.state.engine_client_factory = boom
    app.state.scout_client_factory = boom
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["stale"] == []


def test_engine_on_code_older_than_the_guard_is_stale(client, app, monkeypatch):
    from contracts import build as build_mod
    monkeypatch.setattr(build_mod, "checkout_build_id", lambda: "new1")
    app.state.build = {"build": "new1", "contract_version": 12}
    eng = SimpleNamespace(_public=lambda: SimpleNamespace(process_build=lambda: None),
                          status=lambda: SimpleNamespace(running=True))
    app.state.engine_client_factory = lambda: eng
    app.state.scout_client_factory = lambda: SimpleNamespace(_public=lambda: SimpleNamespace())
    assert client.get("/api/health").json()["stale"] == ["engine"]
