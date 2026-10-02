# copycat architecture

Self-hosted, one trader. Mirror up to 10 Hyperliquid wallets with your own
leverage and sizing. No AI anywhere.

```
            ┌──────────────┐  data/settings.json (api writes, engine reads)
 browser ──▶│ web (Next.js)│──HTTP──▶ api (FastAPI) ──▶ engine.public / discovery.public (read)
            └──────────────┘                │
                                            └─ writes settings, triggers discovery runs
 engine worker  ── every poll_interval_s ──▶ hl (HlVenue) ──▶ Hyperliquid /info + /exchange
 discovery job  ── on demand / nightly   ──▶ hl (reads only) + engine.sizing (pure)
```

## Services (one concern, one directory)

| dir | owns | public surface |
|---|---|---|
| `contracts/` | pydantic models, `Venue` Protocol | `models.py`, `venue.py` |
| `services/hl` | every Hyperliquid call, timeouts, meta cache, signing with the agent key | `hl.HlVenue` implements `contracts.venue.Venue` |
| `services/engine` | copy logic, engine state (`data/engine.db`), event log (`data/events.jsonl`), worker loop | `engine.public`: `run_forever()`, `run_cycle()`, `status() -> EngineStatus`, `events(limit, since_ms) -> list[EngineEvent]`; `engine.sizing`: pure sizing/leverage functions |
| `services/discovery` | leaderboard pull, fills cache (`data/discovery.db`), copy-sim, scoring | `discovery.public`: `start_run(settings, sim_equity_usd, top_n) -> run_id`, `get_run(run_id) -> DiscoveryRun`, `latest() -> DiscoveryRun or None` |
| `services/api` | HTTP API, settings file (only writer), auth | routes below |
| `services/web` | Next.js UI | talks only to the api |

## Settings storage
`data/settings.json` holds `contracts.models.Settings`. The api is the only writer
(atomic write: tmp + os.replace). The engine re-reads it at the start of every
cycle and validates through the model; an invalid file keeps the last good settings
and logs an `error` event.

## API (services/api, prefix /api, JSON)
Auth: header `Authorization: Bearer $COPYCAT_API_TOKEN` on every route except `GET /api/health`.
If `COPYCAT_API_TOKEN` is unset the api refuses to start unless `COPYCAT_BIND=127.0.0.1` (localhost-only dev).

| method | path | body / returns |
|---|---|---|
| GET | /api/health | `{ok, version}` |
| GET | /api/settings | `Settings` |
| PUT | /api/settings | full `Settings` -> `Settings` (validated) |
| PATCH | /api/settings | partial `Settings` -> `Settings`. `leader_overrides` replace per leader; `null` clears one |
| POST | /api/leaders | `{address}` -> `Settings` (409 at 10, 400 bad address) |
| DELETE | /api/leaders/{address} | -> `Settings` (also drops its override) |
| GET | /api/status | `EngineStatus` |
| GET | /api/events?limit=&since_ms= | `EngineEvent[]` newest first |
| GET | /api/events/stream | SSE of `EngineEvent` |
| POST | /api/engine/halt | flips `enabled` false (exits keep mirroring) |
| POST | /api/discovery/runs | `{sim_equity_usd, top_n, settings?}` -> `{run_id}` |
| GET | /api/discovery/runs/latest | `DiscoveryRun` |
| GET | /api/discovery/runs/{id} | `DiscoveryRun` |

## Keys
Hyperliquid API ("agent") wallet: approve it at app.hyperliquid.xyz/API. It can
trade but cannot withdraw. `.env`: `COPYCAT_ACCOUNT_ADDRESS` (your main wallet),
`COPYCAT_AGENT_KEY` (the agent wallet's private key). Never the main wallet's key.

## Running
`docker compose up` runs api, engine worker, web. `make dev` runs them locally.
`make test` runs every service's gate tests (<2s each, no network).
`make eval` runs the live read-only evals (engine dry-run against real leaders,
discovery smoke run).
