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
Auth: header `Authorization: Bearer <token>` on every route except `GET /api/health`, on every bind.
There is no unauthenticated mode. Token: `COPYCAT_API_TOKEN` if set (>= 32 chars, "change-me" refused at
startup); if empty, the api generates one into `$COPYCAT_DATA_DIR/api_token` (mode 0600), prints the path,
and reuses it on restart. Host header must be `localhost`, `127.0.0.1` or in `COPYCAT_ALLOWED_HOSTS`
(comma list), else 400 (DNS-rebinding guard). The api drops `COPYCAT_AGENT_KEY` from its env at startup.
`COPYCAT_SKIP_DOTENV=1` makes `python -m api` / `python -m engine` skip loading `.env`.

| method | path | body / returns |
|---|---|---|
| GET | /api/health | `{ok, version}` |
| GET | /api/settings | `Settings` |
| PUT | /api/settings | full `Settings` -> `Settings` (validated) |
| PATCH | /api/settings | partial `Settings` -> `Settings`. `leader_overrides` replace per leader; `null` clears one |
| POST | /api/leaders | `{address}` -> `Settings` (409 at 10, 400 bad address or our own `COPYCAT_ACCOUNT_ADDRESS`) |
| DELETE | /api/leaders/{address} | -> `Settings` (also drops its override) |
| GET | /api/status | `EngineStatus` |
| GET | /api/events?limit=&since_ms= | `EngineEvent[]` newest first |
| GET | /api/events/stream | SSE of `EngineEvent` |
| POST | /api/engine/halt | flips `enabled` false (exits keep mirroring) |
| POST | /api/engine/close-all | flips `enabled` false, then writes `data/close_all.flag` -> `{requested_ms, pending, settings}`. Next engine cycle closes every copy reduce-only (even in dry_run), keeps the flag until none remain, then logs `halt` "close-all complete" |
| POST | /api/discovery/runs | `{sim_equity_usd, top_n, settings?}` -> `{run_id}` (409 if one is running) |
| GET | /api/discovery/runs/latest | `DiscoveryRun` |
| GET | /api/discovery/runs/{id} | `DiscoveryRun` (404 unknown id) |
| GET | /api/scout/traders | `TraderPage`. Query (spec section 5): `window` 1d/7d/30d/all, `preset` all/hip3/coin:X, `coin` (repeat), `min_av` `max_av` `min_pnl` `max_pnl`, `style` (repeat), `min_fit` `max_fit` 0..100, `max_dd` 0..100, `min_trips`, `active_within_h`, `hide_flagged`, `q`, `sort` (fit default, sim_return, sim_dd, pnl, roi, account_value, sharpe, max_dd, win_rate, trips, last_active, volume), `order` asc/desc, `limit` 1..200, `offset`. Unknown param or min > max is 422. `in_book` filled from `Settings.leaders`. Weak `ETag` = refresh_id:settings_hash:book, `If-None-Match` -> 304 |
| GET | /api/scout/traders/{address} | `TraderProfile`; 404 not a 0x address or no data; 202 + `ScoutStatus` while discovery builds it (poll) |
| GET | /api/scout/traders/{address}/fills?before_ms=&limit= | `LeaderFillView[]` from the fills cache, `limit` 1..500 (default 100) |
| GET | /api/scout/traders/{address}/orders | `OpenOrderView[]` (raw HL open-order rows are mapped by the api) |
| POST | /api/scout/traders/{address}/what-if | `WhatIfRequest` -> `WhatIfResult`, sim at the current `data/settings.json` + `override`. One at a time per api process, 409 while one runs |
| GET | /api/scout/presets | `ScoutPresets` (coin chips, counts, hip3 count) |
| GET | /api/scout/status | `ScoutStatus` |
| POST | /api/scout/refresh | `ScoutStatus`; 409 if a refresh is running |
| GET | /api/scout/traders/{address}/fingerprint?window_days= | `StrategyFingerprint` (window 7..90, default 30). 404 bad address; 202 + `ScoutStatus` while queued/computing (one at a time, child process, cached 15 min, stale served while refreshing); 429 queue full; 502 compute failed (next GET retries) |
| GET | /api/scout/traders/{address}/trades?limit= | `TradeExample[]` (round trips with entry context) = the 30d fingerprint's examples, `limit` 1..8; 202 while the fingerprint builds |
| GET | /api/scout/traders/{address}/thesis | `Thesis[]`, latest per source, `ta` first then `claude_code`; `[]` if none |
| PUT | /api/scout/traders/{address}/thesis | `{title, markdown, author?}` -> `Thesis` saved with source `claude_code`, server-set `created_ms`. markdown 1..20000 chars; any other field (e.g. `source`) is 422 |
| GET | /api/market/candles?coin=&interval=&start_ms=&end_ms= | bars `{t_ms,o,h,l,c,v}[]` via `discovery.public.candles`; interval in 1m..1d (HL set), end > start, at most 5000 bars, else 422 |

## Processes, data files, HL rate budget
- `data/` must be the same absolute path for every process (`python -m api` / `python -m engine`
  resolve `COPYCAT_DATA_DIR` to an absolute path at startup).
- Files: `settings.json` (api writes), `engine.db` + `events.jsonl` (engine writes), `discovery.db`,
  `close_all.flag` (api writes, engine deletes), `api_token` (api), `engine.lock` (flock held by the one
  engine worker; a second worker on the same dir exits 1), `hl_rate.bucket` (shared HL token bucket).
- Discovery runs execute in a child process spawned by the api (`api.discovery_client.run_child`) with
  `COPYCAT_HL_PRIORITY=background` and no agent key: its HL reads only take rate tokens while the
  engine's reserve (`COPYCAT_HL_RESERVE_FRAC`, default 40%) stays in the shared bucket, and its CPU never
  competes with the api's halt/close-all routes. The api reads results from `discovery.db`.
- Scout: `python -m discovery.scout serve` (Makefile `dev`, compose service `scout`) is its own process,
  `COPYCAT_HL_PRIORITY=background`, no agent key, the single writer of the `scout_*` tables in
  `discovery.db`. The api only reads them through `discovery.scout.public` (`api.scout_client`), on
  FastAPI's threadpool (sync routes), never on the event loop. what-if (one wallet, cached data) also
  runs on the threadpool, one at a time. The first Scout call flips the api process to
  `COPYCAT_HL_PRIORITY=background` so the few live reads it makes (open orders) never touch the engine's reserve.

## Keys
Hyperliquid API ("agent") wallet: approve it at app.hyperliquid.xyz/API. It can
trade but cannot withdraw. `.env`: `COPYCAT_ACCOUNT_ADDRESS` (your main wallet),
`COPYCAT_AGENT_KEY` (the agent wallet's private key). Never the main wallet's key.

## Running
`docker compose up` runs api, engine worker, scout scheduler, web. `make dev` runs them locally.
`make test` runs every service's gate tests (<2s each, no network).
`make eval` runs the live read-only evals (engine dry-run against real leaders,
discovery smoke run).
