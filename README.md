# copycat

Self-hosted copy trading for Hyperliquid. Pick up to 25 traders and copycat mirrors
their positions on your account, with **your** leverage and **your** sizing. A
leader opens BTC long at 3x with $2M; you open BTC long at the leverage and margin
you chose. When they close, you close.

**Scout** ranks Hyperliquid traders by what copying them would have earned
*you*: it replays each candidate's real fills through the same sizing and leverage
rules the engine uses, at your account size. Not their PnL. Yours.

One trader, one machine, your keys. No AI, no hosted service, no telemetry. See
[Security model in two minutes](#security-model-in-two-minutes) for what that
means in practice: what the agent key can and cannot do, where keys live, and
what the Claude Code MCP integration can and cannot reach.

## Screenshots

<!-- TODO: add screenshots of Trade (/), Portfolio (/portfolio) and Scout (/scout) -->
_Coming soon._

## 5-minute setup

1. **Run it**, either way:
   ```bash
   make install && make dev     # needs uv + Node 22
   # or
   docker compose up -d --build # needs Docker
   ```
2. **Open http://localhost:3000**, not `127.0.0.1:3000`: the api only allows
   the `COPYCAT_WEB_ORIGIN` origin (default `http://localhost:3000`), so every
   write from any other origin fails CORS (`make dev`'s Next.js dev server adds
   its own matching check on top, with a clearer warning in its own log). It
   asks for the api's bearer token: `COPYCAT_API_TOKEN` if you set one, or
   `cat data/api_token` — the api generates one on first start and also prints
   its path to the terminal running `make dev`.
3. **Set up a trading account.** On the Account page, **Create a new account**
   or **Connect an existing account** (that dialog offers **Sign with wallet**
   or **API key**). Three ways in, pick whichever matches what you already have:
   - **Create a new account** — copycat generates a fresh Hyperliquid wallet on
     this machine and encrypts its key with a passphrase you choose. You see
     the private key once, to back up; copycat never shows it again.
   - **Connect an existing account** by signing with MetaMask or Rabby — your
     wallet approves a copycat-generated agent key for your existing
     Hyperliquid account with one signature. copycat never sees your main key.
   - **Connect with an API wallet key** you already made at
     [app.hyperliquid.xyz/API](https://app.hyperliquid.xyz/API): paste your
     main address and that key. copycat refuses a key whose address equals
     your main account's address.

   Prefer `.env`? `cp .env.example .env`, fill `COPYCAT_ACCOUNT_ADDRESS` and
   `COPYCAT_AGENT_KEY` (an API wallet's key, never your main wallet's), then use
   "Import from .env" on the API-key tab above. This is the only path under
   `docker compose`, where only the `engine` container reads `.env`; everywhere
   else the three UI flows above are the normal way in.
4. **Deposit USDC.** The Account page shows your deposit address, a QR code and
   every funding path (from another Hyperliquid account, from an exchange, from
   Arbitrum through the bridge — $5 minimum, and Hyperliquid credits whichever
   address *sends* the deposit, not whatever address you type). Once the
   balance shows up, press **Refresh agent**: Hyperliquid only approves an
   agent wallet for a funded account.
5. **Add traders to copy.** Paste an address on **Trade**, or research and rank
   candidates on **Scout** and add from there.
6. **Keep Dry run on first**, in **Settings**. The engine ships
   `enabled=false, dry_run=true`: in dry run it reads everything for real and
   logs what it *would* do, without placing an order. Watch **Portfolio** and
   the event log for a while.
7. When the intended trades look right, flip **Trading enabled** on and
   **Dry run** off, both in Settings. **Halt** stops new entries at any time
   (exits keep mirroring).

## Risk, in plain words

Read this before you flip Enabled.

- **Max leverage liquidates fast.** The default is the market's max isolated
  leverage. At 20x, a ~5% move against you liquidates the position. At 40x, ~2.5%.
  Roughly: a move of 1/leverage wipes the margin.
- **There are no stop losses.** copycat does not set stops or take-profits. It does
  what the leader does, nothing more.
- **Exits mirror the leader.** You close when they close. If they hold a loser,
  so do you. If you are liquidated before they close, you are out and they are not.
- **This strategy is untested.** Past leader performance and Scout's replay say
  nothing certain about the future. Treat it as an experiment with money you can
  lose.
- **Small accounts lose a whole fixed margin per liquidation.** With fixed-margin
  sizing, every liquidation costs the full margin you assigned to that copy. A few
  in a row is a big share of a small account.
- **Fills differ from the leader's.** You enter after them, at a worse price and
  with fees. `max_worse_entry_pct` skips entries that have moved too far.
- **This is not a Hyperliquid vault.** No lockup, no profit share, nothing
  pooled with other users. It is your own Hyperliquid account, traded by an
  agent key only you hold; "Add to book" on a trader is copycat replaying
  their trades on your account, not a deposit into anything of theirs.

## Security model in two minutes

- **The agent key can trade. It cannot withdraw.** Every trade copycat places
  is signed by a Hyperliquid *agent* wallet, a key type Hyperliquid itself
  restricts to placing and cancelling orders — it has no authority to move
  funds out, however it was created (copycat-generated, approved by your
  browser wallet, or pasted in from app.hyperliquid.xyz/API). Moving funds
  (deposit, move, withdraw, send) always requires your *main* key: a
  passphrase for a copycat-created wallet, or your browser wallet's own
  signature for a connected one.
- **Keys live in `data/vault/`, encrypted at rest, never in `.env` as plain
  text.** A created wallet's agent key is sealed with a machine key generated
  on first use; its main key is sealed with scrypt (N=2^17) from your
  passphrase, so an offline guess costs real time and memory. A key is
  decrypted only in memory, only for the one signing call that needs it
  (a trade, an approval, a transfer), never written back out. The `api`
  process drops `COPYCAT_AGENT_KEY` from its own environment at startup, so a
  `.env` migration never leaves the key sitting in its process table. See
  `services/vault/README.md` for the full threat model.
- **The web only ever talks to your own api**, over a bearer token you paste
  once (stored in this browser's `localStorage`, nowhere else) and the api
  checks on every request. The api binds to `127.0.0.1` and only accepts the
  configured `COPYCAT_WEB_ORIGIN`, so another site open in your browser cannot
  reach it either.
- **The Claude Code MCP integration gets a second, narrower token**
  (`COPYCAT_MCP_TOKEN`), scoped server-side to research, thesis writes and
  copy-plan creation: it cannot flip `enabled`/`dry_run`, change global
  settings, close a position, or read the admin token. A copy plan it builds
  needs a one-time confirm code to execute, and that code is shown only in
  copycat's own UI (Portfolio → Pending MCP plans) — the model never sees it,
  so a prompt injection in a trader's name or thesis text cannot approve a
  trade by itself. See `services/mcp/README.md`.

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
| `services/vault` | the only owner of secrets: trading accounts, encrypted keys, funding actions |
| `services/engine` | copy logic and the worker loop |
| `services/discovery` | leaderboard pull (Scout), copy simulation, ranking |
| `services/api` | HTTP api, the only writer of settings, bearer-token auth |
| `services/web` | the UI; talks only to the api |
| `services/mcp` | Claude Code integration: thesis research and copy plans, a scoped token |

Full design, routes and storage: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running, testing, evals

```bash
make help      # every target
make install   # .venv via uv + npm ci in services/web
make dev       # api + engine + scout + web together; Ctrl-C stops all four
make test      # gate: pytest (no network, <2s) + web lint, typecheck, vitest
make eval      # live, read-only evals against real Hyperliquid (pytest -m live)
make e2e-demo  # Playwright, web only in demo mode, on a throwaway stack (e2e/README.md)
make e2e       # e2e-demo, then the whole product against the mock Hyperliquid: connect, go live, copy, mirror
make openapi   # regenerate services/api/openapi.json + web client types after a route change
make up        # docker compose up -d --build
make down      # docker compose down
```

`make dev` assumes the api on 8787 and the web on 3000. If you change
`COPYCAT_API_PORT` in `.env`, run `make dev API_PORT=<same port>` so the web
points at it. If you change `WEB_PORT` (`make dev WEB_PORT=3005`), the api's
allowed origin follows automatically; a plain `make dev` is unaffected.

CI (`.github/workflows/ci.yml`) runs the Python gate on 3.13, the web lint,
typecheck, tests and build on Node 22, and fails if `openapi.json` or the
generated web types are stale.

## Docker notes

- `docker compose up` runs `api`, `engine`, `scout` and `web`. State lives in
  `./data` (settings, engine state, event log, discovery cache).
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
make mcp-install RUN=1        # registers the copycat MCP server + /copycat-thesis + /copycat-copy
# then in Claude Code:
/copycat-thesis 0x<trader address>
/copycat-copy 0x<trader address> 50     # strategy + thesis at $50, then a copy plan
```

Claude Code pulls the fingerprint, trades and candles through copycat, writes
the thesis and saves it; it shows on the trader's Strategy tab. The MCP server
reads settings, wallets and scout data, previews a copy and can build a copy
plan, but can never enable trading, change global settings, add or remove a
trader to copy directly, or close positions — see
[Security model in two minutes](#security-model-in-two-minutes).

`/copycat-copy` explains the trader's strategy at your amount, asks for your
leverage, entry deviation, copy/counter and follow/one-shot, and builds a copy
plan (engine preview, warnings, a 6-character confirm code, valid 300 s, single
use). Executing it is OFF by default. To allow it, set
`COPYCAT_MCP_ALLOW_TRADING=1` in BOTH the api's env (or `.env`, then restart the
api) and the MCP server's env (`claude mcp add copycat -s user -e
COPYCAT_MCP_ALLOW_TRADING=1 -- .../run.sh`); `COPYCAT_MCP_MAX_USD` caps each plan
(default $100). Execution writes the same per-wallet terms as the Trade page;
the engine places orders only if trading is enabled and not dry-run. See
services/mcp/README.md.
