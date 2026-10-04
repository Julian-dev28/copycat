# copycat

Self-hosted copy trading for Hyperliquid. Pick up to 10 wallets and copycat mirrors
their positions on your account, with **your** leverage and **your** sizing. A
leader opens BTC long at 3x with $2M; you open BTC long at the leverage and margin
you chose. When they close, you close.

**Discover** ranks Hyperliquid traders by what copying them would have earned
*you*: it replays each candidate's real fills through the same sizing and leverage
rules the engine uses, at your account size. Not their PnL. Yours.

One trader, one machine, your keys. No AI, no hosted service, no telemetry.

## Screenshots

<!-- TODO: add screenshots of /copy, /positions and /discover -->
_Coming soon._

## 5-minute setup

1. **Create an API wallet.** Go to [app.hyperliquid.xyz/API](https://app.hyperliquid.xyz/API),
   generate an API ("agent") wallet and approve it. It can place orders for your
   account but **cannot withdraw**. Copy its private key. Never use your main
   wallet's key.
2. **Fill `.env`.**
   ```bash
   cp .env.example .env
   ```
   Map what you already have onto these variables:

   | variable | what goes in it |
   |---|---|
   | `COPYCAT_ACCOUNT_ADDRESS` | your **main** account address, the one holding the USDC |
   | `COPYCAT_AGENT_KEY` | the private key of the API wallet you approved in step 1. **Not** your main wallet's key: copycat refuses a key whose address equals `COPYCAT_ACCOUNT_ADDRESS` |
   | `COPYCAT_API_TOKEN` | `openssl rand -hex 32`, or leave it empty and the api generates one into `data/api_token`. At least 32 characters; `change-me` is rejected |

3. **Run it**, either way:
   ```bash
   make install && make dev     # needs uv + Node 22
   # or
   docker compose up -d --build # needs Docker
   ```
4. **Open http://localhost:3000** and paste your api token when asked: the
   `COPYCAT_API_TOKEN` you set, or `cat data/api_token` if you left it empty.
5. **Add leaders** on the Copy page (paste addresses), or open **Discover**, run a
   ranking and add from there.
6. **Keep Dry run on first.** The engine ships `enabled=false, dry_run=true`. In dry
   run it reads everything for real and logs what it *would* do, without placing an
   order. Watch **Positions** and the event log for a while.
7. When the intended trades look right, flip **Enabled** and turn Dry run off.
   **Halt** stops new entries at any time (exits keep mirroring).

Use `http://localhost:3000`, not `127.0.0.1:3000`: the api only allows the
`COPYCAT_WEB_ORIGIN` origin (default `http://localhost:3000`).

## Risk, in plain words

Read this before you flip Enabled.

- **Max leverage liquidates fast.** The default is the market's max isolated
  leverage. At 20x, a ~5% move against you liquidates the position. At 40x, ~2.5%.
  Roughly: a move of 1/leverage wipes the margin.
- **There are no stop losses.** copycat does not set stops or take-profits. It does
  what the leader does, nothing more.
- **Exits mirror the leader.** You close when they close. If they hold a loser,
  so do you. If you are liquidated before they close, you are out and they are not.
- **This strategy is untested.** Past leader performance and Discover's replay say
  nothing certain about the future. Treat it as an experiment with money you can
  lose.
- **Small accounts lose a whole fixed margin per liquidation.** With fixed-margin
  sizing, every liquidation costs the full margin you assigned to that copy. A few
  in a row is a big share of a small account.
- **Fills differ from the leader's.** You enter after them, at a worse price and
  with fees. `max_worse_entry_pct` skips entries that have moved too far.

## Architecture

```
browser ─▶ web (Next.js) ─HTTP─▶ api (FastAPI) ─▶ data/settings.json
engine worker ── every poll_interval_s ──▶ Hyperliquid /info + /exchange
discovery job ── on demand ──▶ Hyperliquid (reads only) + engine sizing (pure)
```

| dir | what |
|---|---|
| `contracts/` | shared pydantic models and the `Venue` protocol |
| `services/hl` | every Hyperliquid call, rate limiting, signing with the agent key |
| `services/engine` | copy logic and the worker loop |
| `services/discovery` | leaderboard pull, copy simulation, ranking |
| `services/api` | HTTP api, the only writer of settings, bearer-token auth |
| `services/web` | the UI; talks only to the api |

Full design, routes and storage: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running, testing, evals

```bash
make help      # every target
make install   # .venv via uv + npm ci in services/web
make dev       # api + engine + web together; Ctrl-C stops all three
make test      # gate: pytest (no network, <2s) + web lint, typecheck, vitest
make eval      # live, read-only evals against real Hyperliquid (pytest -m live)
make openapi   # regenerate services/api/openapi.json + web client types after a route change
make up        # docker compose up -d --build
make down      # docker compose down
```

`make dev` assumes the api on 8787 and the web on 3000. If you change
`COPYCAT_API_PORT` in `.env`, run `make dev API_PORT=<same port>` so the web
points at it.

CI (`.github/workflows/ci.yml`) runs the Python gate on 3.13, the web lint,
typecheck, tests and build on Node 22, and fails if `openapi.json` or the
generated web types are stale.

## Docker notes

- `docker compose up` runs `api`, `engine` and `web`. State lives in `./data`
  (settings, engine state, event log, discovery cache).
- Only the `engine` container gets `.env` and with it `COPYCAT_AGENT_KEY`; it is the
  only service that signs. The `api` gets an explicit list of variables
  (token, account address, network, web origin) and never sees the key.
- Ports are published on `127.0.0.1` only. The api always requires a bearer token:
  set `COPYCAT_API_TOKEN`, or leave it empty and read the generated one from
  `data/api_token`.
- The web's api URL (`NEXT_PUBLIC_COPYCAT_API`, default `http://localhost:8787`)
  is baked in at build time. Change it, then `docker compose build web`.
- Containers run as uid 1000. On Linux, if `./data` belongs to another user:
  `sudo chown -R 1000:1000 data`.

## Strategy theses with Claude Code (MCP)

Every trader in Scout gets a deterministic TA fingerprint and thesis (no AI).
For a deeper written thesis, let your own Claude Code do the research:

```
make mcp-install RUN=1        # registers the copycat MCP server + /copycat-thesis
# then in Claude Code:
/copycat-thesis 0x<trader address>
```

Claude Code pulls the fingerprint, trades and candles through copycat, writes
the thesis and saves it; it shows on the trader's Strategy tab. The MCP server
can read and add leaders, but can never enable trading, change leverage or close
positions. See services/mcp/README.md.
