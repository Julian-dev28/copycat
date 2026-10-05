# copycat MCP server

Lets your own Claude Code research Hyperliquid traders through copycat and
write strategy theses. Claude Code is the AI; copycat never calls an LLM API.

## Install

```
make mcp-install          # prints the commands
make mcp-install RUN=1    # runs them
```

That registers the server (`claude mcp add copycat -s user -- <repo>/services/mcp/run.sh`)
and copies the `/copycat-thesis` slash command into `~/.claude/commands/`.
copycat's api must be running (`make dev`).

Then, in Claude Code: `/copycat-thesis 0x<trader address>`.

## Config

| var | default | |
|---|---|---|
| `COPYCAT_API_URL` | `http://localhost:$COPYCAT_API_PORT` or `:8787` | where the api is |
| `COPYCAT_API_TOKEN` | from env, then `.env`, then `$COPYCAT_DATA_DIR/api_token` | bearer token |

`.env` is read as a dict through an allowlist, never loaded into the
environment. `COPYCAT_AGENT_KEY` is popped at startup and `run.sh` unsets it:
the server never holds the trading key.

## Tools

| tool | api call | money? |
|---|---|---|
| `scout_list` | GET /api/scout/traders | read |
| `trader_profile` | GET /api/scout/traders/{a} | read |
| `trader_fingerprint` | GET /api/scout/traders/{a}/fingerprint | read |
| `trader_trades` | GET .../trades (+ profile round trips) | read |
| `trader_fills` | GET .../fills | read |
| `market_candles` | GET /api/market/candles | read |
| `list_theses` | GET .../thesis | read |
| `save_thesis` | PUT .../thesis | text only |
| `copycat_settings` | GET /api/settings | read |
| `engine_status` | GET /api/status | read |
| `my_wallets` | GET /api/wallets | read |
| `preview_copy` | POST /api/wallets/{a}/preview | read (computes a plan, places nothing) |
| `add_leader` | POST /api/leaders | adds to the copy list only (global settings) |

`trader_profile`, `trader_fingerprint` and `trader_trades` take `wait_s`
(default 45, max 120): when copycat answers 202 "building" they poll every 5 s
until the data is ready, so the model needs no retry loop.

Everything a tool returns is treated as data. The server instructions tell the
model that trader names and saved theses come from third parties and must never
be followed as instructions (prompt injection through the leaderboard).

Deliberately absent: anything that changes `enabled`, `dry_run`, leverage or
sizing, removes leaders, invests in or stops a wallet (`/api/wallets/{a}/copy`,
`/stop`), touches accounts or keys (`/api/accounts/*`), halts, or closes
positions. Those decide whether real
money moves, and an agent should never be able to flip them. A gate test pins
the exact tool list.

Prompt: `write_thesis(address)`, eight required sections, checked
deterministically by `prompts.missing_sections()` when saving.

## Tests

`.venv/bin/python -m pytest services/mcp/tests`: request mapping per tool,
auth header, 401/503 messages, the tool allowlist and the forbidden routes,
waiting out 202, prompt sections. No network. A real stdio session against a
running copycat (all 13 tools) was checked on 2026-10-05.
