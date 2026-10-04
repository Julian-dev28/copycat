# services/api

FastAPI over HTTP/JSON for the web UI. Owns `data/settings.json` (the only
writer) and the bearer token. Never signs orders, never holds the agent key.

    COPYCAT_SKIP_DOTENV=1 .venv/bin/python -m api      # binds COPYCAT_BIND:COPYCAT_API_PORT
    .venv/bin/python -m pytest services/api            # gate, <1s
    .venv/bin/python -m api.openapi_export             # regenerate openapi.json (gate checks it)

## Routes (prefix /api)

| method | path | notes |
|---|---|---|
| GET | /health | `{ok, version}`, no auth |
| GET / PUT / PATCH | /settings | `Settings`. PATCH semantics below |
| POST | /leaders | `{address}`; 400 bad address or our own account, 409 at 10 leaders |
| DELETE | /leaders/{address} | also drops its override; idempotent |
| GET | /status | `EngineStatus` from `engine.public.status()`; 503 if the engine package is missing |
| GET | /events?limit=&since_ms= | newest first |
| GET | /events/stream | SSE, tails `data/events.jsonl` from its end, one `EngineEvent` JSON per message |
| POST | /engine/halt | `enabled=false`; exits keep mirroring |
| POST | /engine/close-all | `enabled=false`, then writes `data/close_all.flag`; returns `{requested_ms, pending, settings}`. The engine's next cycle closes every copy |
| POST | /discovery/runs | `{sim_equity_usd, top_n, settings?}` -> `{run_id}`; 409 if one is running |
| GET | /discovery/runs/latest, /discovery/runs/{id} | `DiscoveryRun`; 404 when none / unknown |
| GET | /scout/traders | `TraderPage`; filters/sorts below; `in_book` from `Settings.leaders`; `ETag` + 304 |
| GET | /scout/traders/{address} | `TraderProfile`; 404 bad address or no data; 202 + `ScoutStatus` while being built |
| GET | /scout/traders/{address}/fills?before_ms=&limit= | `LeaderFillView[]`, limit 1..500 (100) |
| GET | /scout/traders/{address}/orders | `OpenOrderView[]` (live) |
| POST | /scout/traders/{address}/what-if | `WhatIfRequest` -> `WhatIfResult` at the current settings file; 409 while one runs |
| GET | /scout/presets | `ScoutPresets` |
| GET | /scout/status | `ScoutStatus` |
| POST | /scout/refresh | `ScoutStatus`; 409 if running |
| GET | /scout/traders/{address}/fingerprint?window_days= | `StrategyFingerprint`; 202 while computing; 429 queue full; 502 failed |
| GET | /scout/traders/{address}/trades?limit= | `TradeExample[]` (fingerprint examples, limit 1..8); 202 while computing |
| GET | /scout/traders/{address}/thesis | `Thesis[]`, latest per source (ta, claude_code) |
| PUT | /scout/traders/{address}/thesis | `{title, markdown<=20k, author?}` -> `Thesis` (source claude_code, server time) |
| GET | /market/candles?coin=&interval=&start_ms=&end_ms= | candle bars, <= 5000, 422 on bad interval/range |

## Auth

Every route but `/health` needs `Authorization: Bearer <token>`, on every
bind. No unauthenticated mode. Token: `COPYCAT_API_TOKEN` (>= 32 chars,
"change-me" refused at startup); if empty, one is generated into
`$COPYCAT_DATA_DIR/api_token` (mode 0600, created with O_EXCL), its path is
printed (never the token), and it is reused on restart. Compared in constant
time. `TrustedHostMiddleware` rejects any Host other than `localhost`,
`127.0.0.1` or `COPYCAT_ALLOWED_HOSTS` with 400 (DNS rebinding). CORS allows
only `COPYCAT_WEB_ORIGIN`. `create_app()` pops `COPYCAT_AGENT_KEY` from the
process env.

## Settings file

`SettingsStore`: every write is tmp file + fsync + `os.replace`, every
read-modify-write under an flock on `settings.json.lock`, so concurrent
PATCHes never lose an update. A missing file serves defaults
(`enabled=false, dry_run=true`). PATCH:
- only fields present in the body change (`model_fields_set`, not `is None`)
- `leaders`, if present, replaces the whole list
- `leader_overrides` merges per leader: a value replaces that leader's whole
  override, `null` clears it
- the merged result is validated through `Settings` before writing; invalid
  is 422 and nothing is written
- a `leaders` list containing `COPYCAT_ACCOUNT_ADDRESS` is 400

## Discovery

Runs execute in a spawned child process (`api.discovery_client.run_child`)
with `COPYCAT_HL_PRIORITY=background`, the absolute data dir, and no agent
key. The child sends back the run id (or busy/error) over a pipe and lives
until the run finishes. The api reads progress from `discovery.db` via
`discovery.public.get_run/latest`. Keeps discovery's CPU and HL reads away
from the halt/close-all routes and the engine's rate reserve.

## Scout

Spec: `docs/research/copytrading_page_spec.md` sections 5, 7.3, 8. Routes in
`api/routes/scout.py`, adapter in `api/scout_client.py` (lazy import of
`discovery.scout.public`; 503 when it isn't importable, its `ScoutBusy` ->
409). Tests use `tests/api_fakes.FakeScoutClient`.

`GET /scout/traders` query params, validated by `api.schemas.ScoutQuery` and
passed to `scout_page(query)` as a plain dict with exactly these keys:

| param | type | default |
|---|---|---|
| window | `1d` `7d` `30d` `all` | `30d` |
| preset | `all`, `hip3`, `coin:<COIN>` | `all` |
| coin, style | repeatable; style in algo/scalp/intraday/swing/position | `[]` |
| min_av, max_av | USD >= 0 | none |
| min_pnl, max_pnl | USD | none |
| min_fit, max_fit | 0..100 | none |
| max_dd | 0..100 (%) | none |
| min_trips | >= 0 | none |
| active_within_h | 1..8784 | none |
| hide_flagged | bool | false |
| q | 1..64 chars, stripped | none |
| sort | fit, sim_return, sim_dd, pnl, roi, account_value, sharpe, max_dd, win_rate, trips, last_active, volume | fit |
| order | asc, desc | desc |
| limit, offset | 1..200, >= 0 | 50, 0 |

Unknown params and any min > max are 422 (a typo'd filter must not look
like "no filter"). Repeated coin/style values are deduped.

Where it runs: the board is built by a separate process,
`python -m discovery.scout serve` (`make dev`, compose `scout`), background
HL priority, no agent key. The api only reads: every Scout route is a sync
`def`, so FastAPI runs it on its threadpool, never on the event loop that
serves halt/close-all. Reads are one SQL query or a stored blob, so a
spawned child per request would cost more than the read. what-if is one
wallet's sim on cached data (seconds), also on the threadpool, guarded by
`app.state.scout_what_if_lock` (non-blocking: second request is 409, never
queued). The first real Scout call sets `COPYCAT_HL_PRIORITY=background` in
the api process, so live reads such as open orders only spend down to the
engine's reserve. Orders are typed `OpenOrderView`; the adapter maps raw HL
`frontendOpenOrders` rows (camelCase strings) if discovery passes those on.

## Strategy theses

Routes in `api/routes/thesis.py`, adapter `api/thesis_client.py` (lazy
`discovery.thesis.public`). `fingerprint()` is slow (fills + candles), so it
never runs in a request: `api/fingerprint_jobs.FingerprintJobs`
(`app.state.fingerprint_jobs`) queues it (dedupe per address+window, max 16
pending -> 429), one worker thread runs one at a time, and the work itself
is a spawned child (`thesis_client.fingerprint_child`, background HL
priority, no agent key) that also refreshes and saves the "ta" thesis.
Results are cached in memory 15 min; a stale one is served while a refresh
runs; a failure is reported once (502/503) and the next GET retries.

`/trades` returns `TradeExample`, not `RoundTrip`: the entry context is
what a thesis needs. They are the 30d fingerprint's examples (max 8). The
full context-free trip list is `TraderProfile.recent_trips`.

PUT thesis takes only `{title, markdown, author?}` (extra="forbid"): the
server sets `source="claude_code"`, `address`, `created_ms`, and links
`fingerprint_as_of_ms` to the cached 30d fingerprint. A client can never
write a "ta" thesis.

`GET /market/candles` (`api/routes/market.py`, `api/market_client.py`) calls
`discovery.public.candles(coin, interval, start_ms, end_ms)`; 503 until
discovery exposes it.
