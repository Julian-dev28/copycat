"""Audit M12: GET /api/health names the processes running older code than
what is on disk for them, each against the packages it imports."""
from __future__ import annotations

from types import SimpleNamespace

from api import build_skew
from api.schemas import ComponentBuild


def c(name, build="abc", cv=12, alive=True, checkout="abc"):
    return ComponentBuild(component=name, build=build, contract_version=cv, alive=alive, checkout=checkout)


def test_same_build_as_disk_everywhere_is_not_stale():
    assert build_skew.stale(c("api"), [c("engine"), c("scout")]) == []
    # ids differ between components by design (different packages): never compared across
    assert build_skew.stale(c("api", build="a1", checkout="a1"), [c("engine", build="e1", checkout="e1")]) == []


def test_other_build_unknown_build_or_contract_is_stale_only_when_running():
    api = c("api")
    others = [c("engine", build="old", checkout="new"), c("scout", build=None), c("x", cv=11),
              c("y", build="old", checkout="new", alive=False)]
    assert build_skew.stale(api, others) == ["engine", "scout", "x"]


def test_api_itself_is_stale_when_its_own_packages_moved_on_disk():
    assert build_skew.stale(c("api", build="old0", checkout="new1"),
                            [c("engine", build="e0", checkout="e1")]) == ["api", "engine"]
    assert build_skew.stale(c("api", build="old0", checkout="old0"), [c("engine", build="e0", checkout="e0")]) == []


def test_unknown_checkout_never_raises_a_false_alarm():
    api = c("api", build="a0", checkout=None)
    assert build_skew.stale(api, [c("engine", build="e0", checkout=None)]) == []
    assert build_skew.component("api", {"build": "a0"}, True, "unknown").checkout is None
    assert build_skew.component("api", {"build": "a0"}, True, "").checkout is None
    assert build_skew.component("api", {"build": "a0"}, True, "a0").checkout == "a0"


def test_health_reports_builds_checkouts_and_stale(client, app, monkeypatch):
    app.state.build = {"build": "a1", "contract_version": 12, "started_ms": 1}
    eng_public = SimpleNamespace(process_build=lambda: {"build": "e0", "contract_version": 12,
                                                       "started_ms": 0, "alive": True})
    app.state.engine_client_factory = lambda: SimpleNamespace(_public=lambda: eng_public)
    scout_public = SimpleNamespace(scout_build=lambda: {"build": "s1", "contract_version": 12,
                                                        "started_ms": 2, "alive": True})
    app.state.scout_client_factory = lambda: SimpleNamespace(_public=lambda: scout_public)
    from contracts import build as build_mod
    on_disk = {"api": "a1", "engine": "e1", "scout": "s1"}
    monkeypatch.setattr(build_mod, "checkout_build_id", lambda component, now=None: on_disk[component])
    body = client.get("/api/health").json()
    assert body["stale"] == ["engine"] and body["checkout_build"] == "a1"
    assert [(b["component"], b["build"], b["checkout"]) for b in body["builds"]] == [
        ("api", "a1", "a1"), ("engine", "e0", "e1"), ("scout", "s1", "s1")]


def test_health_never_fails_when_probes_raise(client, app, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    app.state.engine_client_factory = boom
    app.state.scout_client_factory = boom
    from contracts import build as build_mod
    monkeypatch.setattr(build_mod, "checkout_build_id", boom)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["stale"] == [] and r.json()["checkout_build"] is None


def test_engine_on_code_older_than_the_guard_is_stale(client, app, monkeypatch):
    from contracts import build as build_mod
    monkeypatch.setattr(build_mod, "checkout_build_id", lambda component, now=None: "new1")
    app.state.build = {"build": "new1", "contract_version": 12}
    eng = SimpleNamespace(_public=lambda: SimpleNamespace(process_build=lambda: None),
                          status=lambda: SimpleNamespace(running=True))
    app.state.engine_client_factory = lambda: eng
    app.state.scout_client_factory = lambda: SimpleNamespace(_public=lambda: SimpleNamespace())
    assert client.get("/api/health").json()["stale"] == ["engine"]
