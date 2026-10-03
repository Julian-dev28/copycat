"""copycat MCP server: lets the user's own Claude Code research traders and
write strategy theses. Claude Code is the AI; this server is a typed,
read-mostly view of the copycat api over HTTP. It never calls an LLM, never
imports engine or discovery code, never talks to Hyperliquid, and never holds
the agent key.

Write surface, on purpose this small:
  save_thesis  PUT  /api/scout/traders/{a}/thesis   (text only, no money)
  add_leader   POST /api/leaders                    (adds to the copy list only)

Never exposed, and pinned by a gate test (`FORBIDDEN_TOOL_WORDS`): anything
that changes `enabled`, `dry_run`, leverage or sizing (PUT/PATCH /api/settings),
removes leaders, halts, or closes positions (/api/engine/*). Those decide
whether and how much real money is at risk. An agent can be steered by text
it reads (a trader's name, a thesis, a web page), so a prompt-injected or
simply mistaken agent must not be able to turn trading on, raise leverage or
dump positions. The human flips those switches in the web UI.
"""
from __future__ import annotations

import re
import time
from typing import Annotated, Any, Dict, List, Literal, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .api_client import Accepted, ApiError, CopycatApi, RouteMissing
from .config import McpConfig
from .prompts import THESIS_MAX_CHARS, missing_sections, write_thesis_prompt

INSTRUCTIONS = """copycat is a self-hosted Hyperliquid copy-trading app. These tools read its trader
research data (Scout board, trader profiles, deterministic strategy fingerprints, round trips,
fills, candles) and let you save written strategy theses. You can add a wallet to the copy
list, but you cannot turn trading on, change leverage or sizing, halt, or close positions:
the user does that in the copycat web UI. Use the `write_thesis` prompt for the full
research-and-write flow. Timestamps are Unix milliseconds, UTC."""

ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

Window = Literal["1d", "7d", "30d", "all"]
Style = Literal["algo", "scalp", "intraday", "swing", "position"]
Sort = Literal["fit", "sim_return", "sim_dd", "pnl", "roi", "account_value", "sharpe", "max_dd",
               "win_rate", "trips", "last_active", "volume"]
Interval = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
               "4h": 14_400_000, "1d": 86_400_000}
MAX_CANDLES = 500
CURVE_FIELDS = ("pnl_curve", "value_curve", "sim_curve", "daily_pnl")

Address = Annotated[str, Field(description="Trader wallet, 0x + 40 hex chars.")]

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def norm_address(address: str) -> str:
    a = address.strip()
    if not ADDR_RE.match(a):
        raise ToolError(f"Not a wallet address: {address!r}. Expected 0x followed by 40 hex characters.")
    return a.lower()


def _summarize_curve(points: Any) -> Any:
    if not isinstance(points, list) or not points:
        return {"points": 0}
    return {"points": len(points), "first": points[0], "last": points[-1]}


def trim_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the long time series with point count + first/last. A full
    profile is ~1.5k curve points; the analysis needs the stats, not the plot."""
    out = dict(profile)
    for k in CURVE_FIELDS:
        v = out.get(k)
        if isinstance(v, dict):
            out[k] = {w: _summarize_curve(p) for w, p in v.items()}
        elif v is not None:
            out[k] = _summarize_curve(v)
    out["_note"] = "curves summarized; call trader_profile(include_curves=true) for the full series"
    return out


def build_server(config: Optional[McpConfig] = None, api: Optional[CopycatApi] = None) -> MCPServer:
    config = config or McpConfig.from_env()
    api = api or CopycatApi(config)
    mcp = MCPServer(name="copycat", instructions=INSTRUCTIONS, version="0.1.0")

    async def call(method: str, path: str, **kw: Any) -> Any:
        try:
            return await api.request(method, path, **kw)
        except ApiError as e:
            raise ToolError(str(e)) from e

    def building(body: Any, what: str) -> Dict[str, Any]:
        return {"status": "building", "scout_status": body,
                "hint": f"copycat is still building this trader's {what}. Wait ~30 s and call again."}

    # ── Scout research (read-only) ─────────────────────────────────────

    @mcp.tool(annotations=READ)
    async def scout_list(
        window: Annotated[Window, Field(description="Performance window for perf columns and sorting.")] = "30d",
        sort: Annotated[Sort, Field(description="Sort key. 'fit' = Copy Fit score (how copyable at the "
                                                "user's settings); 'sim_return' = simulated copy return.")]
        = "fit",
        style: Annotated[Optional[List[Style]], Field(description="Only these trading styles.")] = None,
        coin: Annotated[Optional[List[str]], Field(description="Only traders active in these coins, "
                                                               "e.g. ['BTC','ETH'].")] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Rows to return.")] = 20,
        order: Annotated[Literal["asc", "desc"], Field(description="Sort direction.")] = "desc",
        min_trips: Annotated[Optional[int], Field(ge=0, description="Minimum round trips in the "
                                                                    "window (sample size).")] = None,
        hide_flagged: Annotated[bool, Field(description="Hide traders with warning flags.")] = False,
    ) -> Dict[str, Any]:
        """List traders on copycat's Scout board (Hyperliquid leaderboard wallets scored for
        copyability). Each row has account value, style, per-window PnL/ROI, top coins, a
        simulated copy score at the user's settings, flags, and whether it is already copied
        (`in_book`). Start here to find candidates, then call trader_profile / trader_fingerprint."""
        params: Dict[str, Any] = {"window": window, "sort": sort, "order": order, "limit": limit,
                                  "style": style, "coin": [c.strip() for c in coin or [] if c.strip()],
                                  "min_trips": min_trips}
        if hide_flagged:
            params["hide_flagged"] = "true"
        return await call("GET", "/api/scout/traders", params=params)

    @mcp.tool(annotations=READ)
    async def trader_profile(
        address: Address,
        include_curves: Annotated[bool, Field(description="Return full PnL/value/sim/daily curves "
                                                          "(large). Default: summarized.")] = False,
    ) -> Dict[str, Any]:
        """One trader's file: board row, account risk (leverage, margin use, nearest liquidation),
        open positions, risk stats (7d/30d/all), trade stats, coins, recent round trips and fills.
        Curves are summarized unless include_curves=true. If copycat is still building the
        profile, returns status "building": wait and retry."""
        res = await call("GET", f"/api/scout/traders/{norm_address(address)}")
        if isinstance(res, Accepted):
            return building(res.body, "profile")
        return res if include_curves else trim_profile(res)

    @mcp.tool(annotations=READ)
    async def trader_fingerprint(address: Address) -> Dict[str, Any]:
        """The deterministic strategy fingerprint, computed by copycat from fills and candles (no AI):
        style, hold times, long share, entry habits (% trend-aligned / breakout / pullback, RSI at
        entry), sizing (adds, scale in/out, avg/max leverage), outcomes (win rate, payoff ratio,
        loser-vs-winner hold, worst trip % of equity, coin concentration), UTC hour and weekday
        histograms, tags, a templated summary, up to 8 example trades with entry context, and
        caveats. `trips_analyzed` is the sample size: weigh every claim by it."""
        res = await call("GET", f"/api/scout/traders/{norm_address(address)}/fingerprint")
        if isinstance(res, Accepted):
            return building(res.body, "fingerprint")
        return res

    @mcp.tool(annotations=READ)
    async def trader_trades(
        address: Address,
        limit: Annotated[int, Field(ge=1, le=200, description="Most recent round trips to return.")] = 50,
    ) -> Dict[str, Any]:
        """Recent round trips (open -> close of one position) newest first: coin, side, open/close
        time, hold hours, entry/exit price, max notional, net PnL after fees, and the market
        context at entry (trend-aligned, breakout, pullback, RSI-14, 24h move, UTC hour) where
        candles exist. Falls back to the profile's recent_trips (no entry context) on an older
        api build."""
        a = norm_address(address)
        try:
            res = await api.request("GET", f"/api/scout/traders/{a}/trades", params={"limit": limit})
        except RouteMissing:
            prof = await call("GET", f"/api/scout/traders/{a}")
            if isinstance(prof, Accepted):
                return building(prof.body, "profile")
            trips = (prof.get("recent_trips") or [])[:limit]
            return {"trades": trips, "entry_context": False,
                    "note": "this api build has no /trades route; these are profile.recent_trips "
                            "without entry context"}
        except ApiError as e:
            raise ToolError(str(e)) from e
        if isinstance(res, Accepted):
            return building(res.body, "trades")
        return {"trades": res, "entry_context": True} if isinstance(res, list) else res

    @mcp.tool(annotations=READ)
    async def trader_fills(
        address: Address,
        before_ms: Annotated[Optional[int], Field(ge=0, description="Only fills strictly before this "
                                                                    "time (ms). Page backwards with the "
                                                                    "oldest time_ms you got.")] = None,
        limit: Annotated[int, Field(ge=1, le=500, description="Fills per page.")] = 100,
    ) -> Dict[str, Any]:
        """Raw fills (newest first) from copycat's fills cache: time, coin, side (B buy / A sell),
        direction (Open Long, Close Short, ...), price, size, notional, closed PnL, fee. Use when a
        round trip needs fill-level detail (adds, partial exits)."""
        res = await call("GET", f"/api/scout/traders/{norm_address(address)}/fills",
                         params={"before_ms": before_ms, "limit": limit})
        return {"fills": res}

    @mcp.tool(annotations=READ)
    async def market_candles(
        coin: Annotated[str, Field(min_length=1, max_length=32, description="Hyperliquid coin, e.g. 'BTC'.")],
        interval: Annotated[Interval, Field(description="Candle interval.")] = "1h",
        start_ms: Annotated[Optional[int], Field(ge=0, description="Start, Unix ms UTC. Default: "
                                                                   "100 bars before end_ms.")] = None,
        end_ms: Annotated[Optional[int], Field(ge=0, description="End, Unix ms UTC. Default: now.")] = None,
    ) -> Dict[str, Any]:
        """OHLCV candles for one coin from copycat (its candle cache), at most 500 bars per call.
        Use to see price action around a trader's entry: e.g. 1h bars from 48h before opened_ms
        to a few hours after closed_ms."""
        step = INTERVAL_MS[interval]
        end = end_ms if end_ms is not None else int(time.time() * 1000)
        start = start_ms if start_ms is not None else end - 100 * step
        if start >= end:
            raise ToolError(f"start_ms ({start}) must be before end_ms ({end}).")
        bars = (end - start) // step
        if bars > MAX_CANDLES:
            raise ToolError(f"That range is {bars} {interval} bars; the limit is {MAX_CANDLES}. "
                            f"Use a larger interval or a shorter range.")
        res = await call("GET", "/api/market/candles",
                         params={"coin": coin.strip(), "interval": interval, "start_ms": start,
                                 "end_ms": end})
        return {"coin": coin.strip(), "interval": interval, "start_ms": start, "end_ms": end,
                "candles": res}

    # ── Theses ─────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ)
    async def list_theses(address: Address) -> Dict[str, Any]:
        """Saved strategy theses for a trader, both the deterministic "ta" one and any written by
        Claude Code ("claude_code"), with title, markdown, author and creation time. Read these
        before writing a new one."""
        res = await call("GET", f"/api/scout/traders/{norm_address(address)}/thesis")
        return {"theses": res}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                          idempotent_hint=True, open_world_hint=False))
    async def save_thesis(
        address: Address,
        title: Annotated[str, Field(min_length=1, max_length=200, description="Short title, e.g. "
                                                                              "'BTC breakout swing trader'.")],
        markdown: Annotated[str, Field(min_length=1, description="The full thesis in markdown, with the "
                                                                 "write_thesis prompt's ## sections.")],
        fingerprint_as_of_ms: Annotated[Optional[int], Field(description="as_of_ms of the fingerprint "
                                                                         "the thesis is based on.")] = None,
        author: Annotated[Optional[str], Field(max_length=120, description="Who wrote it, e.g. "
                                                                           "'claude-opus-5-5 via copycat MCP'.")]
        = None,
    ) -> Dict[str, Any]:
        """Save a Claude Code strategy thesis for a trader in copycat (source "claude_code"), shown
        on the trader's page. Replaces this source's previous thesis for the trader. Text only:
        it changes nothing about copying or trading. The result lists any required sections the
        markdown is missing; if so, fix and save again."""
        if len(markdown) > THESIS_MAX_CHARS:
            raise ToolError(f"Thesis is {len(markdown)} chars; the limit is {THESIS_MAX_CHARS}. Shorten it.")
        body = {"source": "claude_code", "title": title.strip(), "markdown": markdown,
                "author": (author or config.author).strip(), "fingerprint_as_of_ms": fingerprint_as_of_ms}
        res = await call("PUT", f"/api/scout/traders/{norm_address(address)}/thesis", json=body)
        missing = missing_sections(markdown)
        return {"saved": res, "missing_sections": missing,
                "ok": not missing}

    # ── Settings and copy list ─────────────────────────────────────────

    @mcp.tool(annotations=READ)
    async def copycat_settings() -> Dict[str, Any]:
        """Read-only view of copycat's current settings: enabled, dry_run, the copy list (leaders),
        sizing mode and amounts, leverage mode and cap, margin mode, per-leader overrides and risk
        limits. This server cannot change any of them; the user does that in the copycat web UI."""
        return await call("GET", "/api/settings")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                          idempotent_hint=True, open_world_hint=False))
    async def add_leader(address: Address) -> Dict[str, Any]:
        """Add a wallet to copycat's copy list (max 10). This ONLY adds it to the list. Whether
        copycat actually trades is governed by the `enabled` and `dry_run` settings, which this
        server can never change: with enabled=false or dry_run=true nothing is ordered. Only add a
        leader when the user asked for it. Returns the updated settings."""
        res = await call("POST", "/api/leaders", json={"address": norm_address(address)})
        return {"settings": res,
                "note": "added to the copy list only. Trading is governed by enabled/dry_run "
                        f"(currently enabled={res.get('enabled')}, dry_run={res.get('dry_run')}), "
                        "which only the user can change in the web UI."}

    # ── Prompt ────────────────────────────────────────────────────────

    @mcp.prompt(name="write_thesis", description="Research one trader with the copycat tools and save "
                                                 "a strategy thesis.")
    def write_thesis(address: Annotated[str, Field(description="Trader wallet, 0x + 40 hex chars.")]) -> str:
        return write_thesis_prompt(address.strip().lower())

    return mcp
