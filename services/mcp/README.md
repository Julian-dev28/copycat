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
| `add_leader` | POST /api/leaders | adds to the copy list only |

Deliberately absent: anything that changes `enabled`, `dry_run`, leverage or
sizing, removes leaders, halts, or closes positions. Those decide whether real
money moves, and an agent should never be able to flip them. A gate test pins
the exact tool list.

Prompt: `write_thesis(address)`, eight required sections, checked
deterministically by `prompts.missing_sections()` when saving.

## Tests

`.venv/bin/python -m pytest services/mcp/tests`: request mapping per tool,
auth header, 401/503 messages, the tool allowlist, prompt sections. No network.
