"""Gate tests for the copycat MCP server: request mapping, auth, error
surfacing, the tool allowlist, and the write_thesis prompt. No network: the
api is an httpx.MockTransport, the MCP client runs in-process."""
from __future__ import annotations

import os

import httpx
import pytest
from copycat_mcp.config import McpConfig, read_dotenv, scrub_agent_key
from copycat_mcp.prompts import THESIS_MAX_CHARS, THESIS_SECTIONS, missing_sections, write_thesis_prompt
from copycat_mcp.server import trim_profile
from mcp_fakes import ADDR, ADDR_MIXED, TOKEN, FakeApi, call, make_server, run, text

SETTINGS = {"enabled": False, "dry_run": True, "leaders": [], "leverage": 20}

EXPECTED_TOOLS = {"scout_list", "trader_profile", "trader_fingerprint", "trader_trades", "trader_fills",
                  "market_candles", "list_theses", "save_thesis", "copycat_settings", "add_leader"}
# Any tool whose name hints at one of these would let an agent put money at risk.
FORBIDDEN_TOOL_WORDS = ("enable", "dry", "leverage", "sizing", "size", "margin", "halt", "close",
                        "remove", "delete", "patch", "update_settings", "set_", "override", "kill")


def full_thesis(extra: str = "") -> str:
    return "\n\n".join(f"## {s}\nbody" for s in THESIS_SECTIONS) + extra


# ── tool surface ─────────────────────────────────────────────────────────

def test_tool_list_is_exactly_the_allowlist():
    tools = run(make_server(FakeApi()), lambda c: c.list_tools()).tools
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    for n in names:
        assert not any(w in n for w in FORBIDDEN_TOOL_WORDS), n
    for t in tools:
        assert t.description and len(t.description) > 60, t.name


def test_only_two_tools_write_and_none_is_destructive():
    tools = run(make_server(FakeApi()), lambda c: c.list_tools()).tools
    writers = {t.name for t in tools if not (t.annotations and t.annotations.read_only_hint)}
    assert writers == {"save_thesis", "add_leader"}
    for t in tools:
        if t.name in writers:
            assert t.annotations.destructive_hint is False


def test_no_tool_can_reach_settings_writes_or_engine_routes():
    """Call every tool with plausible args; no request may hit a money-moving route."""
    fake = FakeApi(routes={("POST", "/api/leaders"): SETTINGS, ("GET", "/api/settings"): SETTINGS})
    s = make_server(fake)
    args = {"address": ADDR, "coin": "BTC", "title": "t", "markdown": full_thesis()}
    for name in EXPECTED_TOOLS:
        schema = run(s, lambda c: c.list_tools())
        props = next(t for t in schema.tools if t.name == name).input_schema.get("properties", {})
        call(s, name, {k: v for k, v in args.items() if k in props})
    for r in fake.requests:
        assert not (r.method in ("PUT", "PATCH") and r.url.path == "/api/settings"), r
        assert not r.url.path.startswith("/api/engine"), r
        assert r.method != "DELETE", r


def test_add_leader_docstring_states_the_limits():
    tools = run(make_server(FakeApi()), lambda c: c.list_tools()).tools
    d = next(t for t in tools if t.name == "add_leader").description
    assert "ONLY adds" in d and "enabled" in d and "dry_run" in d and "never change" in d


# ── request mapping + auth header ────────────────────────────────────────

def test_scout_list_maps_query_and_sends_bearer():
    fake = FakeApi(routes={("GET", "/api/scout/traders"): {"rows": [], "total": 0}})
    r = call(make_server(fake), "scout_list", {"window": "7d", "sort": "pnl", "style": ["swing", "scalp"],
                                               "coin": ["BTC", " ETH "], "limit": 5, "min_trips": 30,
                                               "hide_flagged": True})
    assert not r.is_error, text(r)
    req = fake.last
    assert req.method == "GET" and req.url.path == "/api/scout/traders"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    q = req.url.params
    assert q["window"] == "7d" and q["sort"] == "pnl" and q["limit"] == "5" and q["order"] == "desc"
    assert q.get_list("style") == ["swing", "scalp"] and q.get_list("coin") == ["BTC", "ETH"]
    assert q["min_trips"] == "30" and q["hide_flagged"] == "true"


def test_scout_list_defaults_omit_unset_filters():
    fake = FakeApi(routes={("GET", "/api/scout/traders"): {"rows": []}})
    call(make_server(fake), "scout_list")
    q = fake.last.url.params
    assert dict(q) == {"window": "30d", "sort": "fit", "order": "desc", "limit": "20"}


def test_profile_lowercases_address_and_trims_curves():
    prof = {"row": {"address": ADDR}, "pnl_curve": {"30d": [{"t_ms": 1, "value": 1}, {"t_ms": 2, "value": 3}]},
            "sim_curve": [{"t_ms": i, "value": i} for i in range(700)], "daily_pnl": [], "value_curve": {}}
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}"): prof})
    r = call(make_server(fake), "trader_profile", {"address": ADDR_MIXED})
    assert fake.last.url.path == f"/api/scout/traders/{ADDR}"
    sc = r.structured_content
    assert sc["sim_curve"] == {"points": 700, "first": {"t_ms": 0, "value": 0}, "last": {"t_ms": 699, "value": 699}}
    assert sc["pnl_curve"]["30d"]["points"] == 2 and sc["daily_pnl"] == {"points": 0}
    full = call(make_server(fake), "trader_profile", {"address": ADDR, "include_curves": True}).structured_content
    assert len(full["sim_curve"]) == 700


def test_profile_202_is_building_not_error():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}"):
                           httpx.Response(202, json={"state": "running", "refresh_id": "r"})})
    r = call(make_server(fake), "trader_profile", {"address": ADDR})
    assert not r.is_error
    assert r.structured_content["status"] == "building"
    assert r.structured_content["scout_status"]["state"] == "running"


def test_fingerprint_path():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}/fingerprint"): {"address": ADDR, "trips_analyzed": 9}})
    r = call(make_server(fake), "trader_fingerprint", {"address": ADDR})
    assert r.structured_content["trips_analyzed"] == 9


def test_trades_route_and_limit():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}/trades"): [{"coin": "BTC"}]})
    r = call(make_server(fake), "trader_trades", {"address": ADDR, "limit": 7})
    assert fake.last.url.params["limit"] == "7"
    assert r.structured_content == {"trades": [{"coin": "BTC"}], "entry_context": True}


def test_trades_falls_back_to_profile_when_route_missing():
    trips = [{"coin": c} for c in "ABC"]
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}"): {"recent_trips": trips}})
    r = call(make_server(fake), "trader_trades", {"address": ADDR, "limit": 2})
    assert not r.is_error, text(r)
    assert r.structured_content["trades"] == trips[:2] and r.structured_content["entry_context"] is False


def test_fills_maps_paging():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}/fills"): [{"coin": "ETH"}]})
    r = call(make_server(fake), "trader_fills", {"address": ADDR, "before_ms": 123, "limit": 250})
    assert dict(fake.last.url.params) == {"before_ms": "123", "limit": "250"}
    assert r.structured_content == {"fills": [{"coin": "ETH"}]}


def test_candles_maps_query_and_caps_bars():
    fake = FakeApi(routes={("GET", "/api/market/candles"): [{"t": 1}]})
    s = make_server(fake)
    r = call(s, "market_candles", {"coin": "BTC", "interval": "1h", "start_ms": 0, "end_ms": 3_600_000 * 48})
    assert dict(fake.last.url.params) == {"coin": "BTC", "interval": "1h", "start_ms": "0",
                                          "end_ms": str(3_600_000 * 48)}
    assert r.structured_content["candles"] == [{"t": 1}]
    n = len(fake.requests)
    big = call(s, "market_candles", {"coin": "BTC", "interval": "1m", "start_ms": 0, "end_ms": 60_000 * 501})
    assert big.is_error and "limit is 500" in text(big) and len(fake.requests) == n
    bad = call(s, "market_candles", {"coin": "BTC", "start_ms": 10, "end_ms": 5})
    assert bad.is_error and "before end_ms" in text(bad)


def test_candles_default_range_is_100_bars():
    fake = FakeApi(routes={("GET", "/api/market/candles"): []})
    call(make_server(fake), "market_candles", {"coin": "ETH", "interval": "15m", "end_ms": 10_000_000})
    assert fake.last.url.params["start_ms"] == str(10_000_000 - 100 * 900_000)


def test_candles_route_missing_is_reported():
    r = call(make_server(FakeApi()), "market_candles", {"coin": "BTC"})
    assert r.is_error and "does not exist in this copycat api build" in text(r)


def test_list_theses_path():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}/thesis"): [{"source": "ta"}]})
    r = call(make_server(fake), "list_theses", {"address": ADDR})
    assert r.structured_content == {"theses": [{"source": "ta"}]}


def test_save_thesis_body_and_section_check():
    fake = FakeApi(routes={("PUT", f"/api/scout/traders/{ADDR}/thesis"): lambda req: httpx.Response(200, json={"ok": 1})})
    r = call(make_server(fake), "save_thesis", {"address": ADDR_MIXED, "title": " BTC swing ",
                                                "markdown": full_thesis(), "fingerprint_as_of_ms": 5})
    body = fake.last_json()
    assert fake.last.method == "PUT" and fake.last.url.path == f"/api/scout/traders/{ADDR}/thesis"
    assert body == {"source": "claude_code", "title": "BTC swing", "markdown": full_thesis(),
                    "author": "claude-code via copycat MCP", "fingerprint_as_of_ms": 5}
    assert r.structured_content["ok"] is True and r.structured_content["missing_sections"] == []

    r2 = call(make_server(fake), "save_thesis", {"address": ADDR, "title": "t", "markdown": "## Exits\nx",
                                                 "author": "claude-opus-5-5 via copycat MCP"})
    assert fake.last_json()["author"] == "claude-opus-5-5 via copycat MCP"
    assert r2.structured_content["ok"] is False and "Edge in one sentence" in r2.structured_content["missing_sections"]


def test_save_thesis_rejects_oversize_without_calling_api():
    fake = FakeApi()
    r = call(make_server(fake), "save_thesis", {"address": ADDR, "title": "t",
                                                "markdown": "x" * (THESIS_MAX_CHARS + 1)})
    assert r.is_error and "limit is 20000" in text(r) and fake.requests == []


def test_thesis_limit_matches_contract():
    from contracts.models import Thesis
    from pydantic import ValidationError
    Thesis(address=ADDR, source="claude_code", created_ms=0, title="t", markdown="x" * THESIS_MAX_CHARS)
    with pytest.raises(ValidationError):
        Thesis(address=ADDR, source="claude_code", created_ms=0, title="t", markdown="x" * (THESIS_MAX_CHARS + 1))


def test_settings_and_add_leader():
    fake = FakeApi(routes={("GET", "/api/settings"): SETTINGS, ("POST", "/api/leaders"): SETTINGS})
    s = make_server(fake)
    assert call(s, "copycat_settings").structured_content == SETTINGS
    assert fake.last.method == "GET"
    r = call(s, "add_leader", {"address": ADDR_MIXED})
    assert fake.last.method == "POST" and fake.last.url.path == "/api/leaders"
    assert fake.last_json() == {"address": ADDR}
    assert "enabled=False, dry_run=True" in r.structured_content["note"]


def test_bad_address_never_reaches_the_api():
    fake = FakeApi()
    for bad in ("0x123", "../settings", "0x" + "g" * 40, ADDR + "/fills"):
        r = call(make_server(fake), "trader_profile", {"address": bad})
        assert r.is_error and "Not a wallet address" in text(r)
    assert fake.requests == []


# ── error surfacing ──────────────────────────────────────────────────────

@pytest.mark.parametrize("status,needle", [
    (401, "set COPYCAT_API_TOKEN"), (403, "set COPYCAT_API_TOKEN"),
    (503, "Start copycat"), (409, "Busy or conflict"), (422, "refused the request"),
    (500, "copycat api error 500"),
])
def test_http_errors_are_actionable(status, needle):
    fake = FakeApi(routes={("GET", "/api/settings"): httpx.Response(status, json={"detail": "why"})})
    r = call(make_server(fake), "copycat_settings")
    assert r.is_error
    assert needle.lower() in text(r).lower()


def test_resource_404_keeps_detail():
    fake = FakeApi(routes={("GET", f"/api/scout/traders/{ADDR}"): httpx.Response(404, json={"detail": "no data"})})
    r = call(make_server(fake), "trader_profile", {"address": ADDR})
    assert r.is_error and "no data" in text(r) and "does not exist" not in text(r)


def test_connection_refused_says_start_copycat():
    r = call(make_server(raise_connect=True), "copycat_settings")
    assert r.is_error and "Start copycat" in text(r) and "localhost:8795" in text(r)


def test_missing_token_says_set_token_and_sends_nothing():
    fake = FakeApi()
    r = call(make_server(fake, token=None), "copycat_settings")
    assert r.is_error and "Set COPYCAT_API_TOKEN" in text(r) and fake.requests == []


def test_token_file_is_read_per_request(tmp_path):
    fake = FakeApi(routes={("GET", "/api/settings"): SETTINGS})
    s = make_server(fake, token=None, data_dir=tmp_path)
    assert call(s, "copycat_settings").is_error              # api not started yet: no file
    (tmp_path / "api_token").write_text("f" * 64 + "\n")
    assert not call(s, "copycat_settings").is_error
    assert fake.last.headers["authorization"] == "Bearer " + "f" * 64


# ── config: agent key never enters ───────────────────────────────────────

def test_dotenv_is_allowlisted_and_agent_key_scrubbed(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COPYCAT_AGENT_KEY=0xsecret\nCOPYCAT_API_TOKEN=" + "k" * 40 + "\nCOPYCAT_API_PORT=9001\n"
                   "COPYCAT_DATA_DIR=rel/data\n")
    assert "COPYCAT_AGENT_KEY" not in read_dotenv(env)
    cfg = McpConfig.from_env({}, dotenv_path=env)
    assert cfg.api_url == "http://localhost:9001" and cfg.env_token == "k" * 40
    assert cfg.data_dir.is_absolute() and cfg.data_dir.parts[-2:] == ("rel", "data")
    assert "COPYCAT_AGENT_KEY" not in os.environ or os.environ["COPYCAT_AGENT_KEY"] != "0xsecret"
    d = {"COPYCAT_AGENT_KEY": "x"}
    assert scrub_agent_key(d) is True and d == {}


def test_env_wins_over_dotenv_and_skip_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COPYCAT_API_TOKEN=" + "k" * 40 + "\n")
    cfg = McpConfig.from_env({"COPYCAT_API_URL": "http://127.0.0.1:8795/", "COPYCAT_API_TOKEN": "e" * 40},
                             dotenv_path=env)
    assert cfg.api_url == "http://127.0.0.1:8795" and cfg.env_token == "e" * 40
    assert McpConfig.from_env({"COPYCAT_SKIP_DOTENV": "1"}, dotenv_path=env).env_token is None
    assert McpConfig.from_env({}, dotenv_path=tmp_path / "nope").api_url == "http://localhost:8787"


def test_server_never_imports_trading_code():
    import sys
    make_server(FakeApi())
    for mod in ("engine", "discovery", "hl", "hyperliquid", "eth_account", "anthropic", "openai"):
        assert not any(m == mod or m.startswith(mod + ".") for m in sys.modules
                       if sys.modules[m] is not None and "copycat_mcp" in getattr(sys.modules[m], "__file__", "") or False)
    src = "".join(p.read_text() for p in __import__("pathlib").Path(__file__).parents[1].joinpath("copycat_mcp").glob("*.py"))
    for banned in ("import engine", "from engine", "import discovery", "from discovery", "from hl",
                   "import hl", "hyperliquid", "anthropic", "openai", "load_dotenv("):
        assert banned not in src, banned


# ── prompt ───────────────────────────────────────────────────────────────

def test_write_thesis_prompt_has_every_section_and_rule():
    res = run(make_server(FakeApi()), lambda c: c.get_prompt("write_thesis", {"address": ADDR_MIXED}))
    body = res.messages[0].content.text
    for s in THESIS_SECTIONS:
        assert f"## {s}" in body, s
    for needle in ("trader_fingerprint", "trader_trades", "market_candles", "3-5 key entries", "save_thesis",
                   "coin, side and UTC date", "Never claim certainty from small samples",
                   "No financial advice", "small accounts", "latency", "leverage", ADDR):
        assert needle in body, needle


def test_prompt_is_listed_with_address_argument():
    prompts = run(make_server(FakeApi()), lambda c: c.list_prompts()).prompts
    p = next(p for p in prompts if p.name == "write_thesis")
    assert [a.name for a in p.arguments] == ["address"] and p.arguments[0].required


def test_missing_sections_matching():
    assert missing_sections(full_thesis()) == []
    md = full_thesis().replace("## Sizing & risk", "### Sizing and Risk (leverage)")
    assert missing_sections(md) == []
    assert missing_sections("Edge in one sentence\nno headings") == list(THESIS_SECTIONS)
    assert missing_sections(full_thesis().replace("## Exits", "## Entries")) == ["Exits"]


def test_prompt_sections_match_checker():
    p = write_thesis_prompt(ADDR)
    assert missing_sections(p) == [] or all(f"`## {s}`" in p for s in THESIS_SECTIONS)


def test_trim_profile_handles_missing_fields():
    assert trim_profile({"row": 1})["row"] == 1
