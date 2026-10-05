# copycat architecture

Self-hosted, one trader. Mirror up to 25 Hyperliquid wallets with your own
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
| `services/vault` | every secret: trading accounts, agent keys (machine-key AES-GCM), created wallets' main keys (passphrase scrypt + AES-GCM), the active account, the money-movement audit log | `vault.public`: `create_account`, `import_api_key`, `import_env`, `prepare_agent_approval`, `submit_agent_approval`, `list_accounts`, `set_active`, `rename`, `remove`, `refresh_agent`, `transfer`, `prepare_user_action`, `submit_user_action`, `run_user_action`, `audit_log`, `active_address`, `active_credentials`. See `services/vault/README.md` (threat model) |
| `services/engine` | copy logic, engine state (`data/engine-<address>.db`, one per trading account), event log (`data/events.jsonl`), worker loop | `engine.public`: `run_forever()`, `run_cycle()`, `status() -> EngineStatus`, `events(limit, since_ms) -> list[EngineEvent]`; `engine.sizing`: pure sizing/leverage functions |
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
| POST | /api/leaders | `{address}` -> `Settings` (409 at 25, 400 bad address or our own `COPYCAT_ACCOUNT_ADDRESS`) |
| DELETE | /api/leaders/{address} | -> `Settings` (also drops its override) |
| GET | /api/status | `EngineStatus` (`effective_poll_s`: the poll interval stretched to the HL read budget) |
| POST | /api/wallets/{address}/copy | `WalletCopyRequest` -> `Settings`. One locked write adds the wallet (409 at 25, 400 bad/own address). `settings_source` global: its override is cleared to `{invested_ms}` only, so it runs on the Settings tab. custom: override = `sizing_mode` allocation + the ticket's terms (+ `leverage_mode`, `leverage`, `only_new_positions`, v8 `trade_direction`, `coin_allowlist`, `coin_blocklist` when given; lists stripped and de-duplicated, [] = no list of its own). `paused` is kept as it was. `invested_ms` = now when new, kept on a re-post or a global/custom switch. 422: custom without `allocation_usd`, or target exposure without `target_leverage`. Cancels a pending stop flag |
| POST | /api/wallets/{address}/preview | `WalletCopyRequest` -> `WalletPreview`: what would be copied of his book now, from `engine.sizing.plan_allocation` (the engine's own sizing) on live reads (his account, max leverage, 24h volume, book depth); a global request uses `engine.sizing.plan_copy` on the book-wide settings (fixed_margin / fixed_notional / proportional sizes per position). 400 bad address, 422 target without leverage, 502 his read failed, 503 engine missing |
| POST | /api/wallets/{address}/stop | `WalletStopRequest` -> `{settings, stopping}`. Removes the wallet + override, writes `data/stop/<address>.flag` `{close_positions, requested_ms}`. close_positions: the engine closes its copies reduce-only (even in dry_run), retrying until flat (`close` "stop wallet", then `skip` "wallet stopped"); else they follow his exits. 404 if neither in the book nor an orphan with copies |
| GET | /api/wallets | `WalletPosition[]`: book wallets, then out-of-book wallets: winding down (orphans with copies or a pending stop) or stopped with a ledger history and not archived. `?include=archived` adds archived ones (from the ledger). Position fields from the engine's last cycle; `roe_pct` = (realized + unrealized) / allocation x 100 (None when not on allocation sizing); `settings_source` global (no per-wallet terms; an override of only `invested_ms`/`paused` counts as global) or custom. v8 `status`: running, paused (effective `paused`), stopping (stop flag pending or a close retrying), stopped (out of the book), archived; `trade_direction`, coin lists, `style` (his Scout board style, null when unknown) |
| POST | /api/wallets/{address}/pause | -> `Settings`. Sets the wallet override's `paused` true (a global wallet gets `{paused}` and stays global). Engine: no opens/adds for it (skip "paused"), exits still mirrored. 404 not in the book |
| POST | /api/wallets/{address}/resume | -> `Settings`. Clears `paused` (None; `false` when the whole book is paused). 404 not in the book |
| POST | /api/wallets/{address}/archive | -> `WalletPosition` (status archived). Only a stopped wallet: not in the book, no stop pending, no copies (409 otherwise, also when the engine still holds a copy row). Sets `archived_ms` in the engine ledger; the engine stops reading it; copying it again un-archives it |
| GET | /api/wallets/{address}/events | `EngineEvent[]`, newest first: that wallet's opens/adds/reduces/closes and skips with reasons. `limit` (1-500, default 50), `before_ms` to page. Read from the tail of `events.jsonl`, scan capped at 8MB |
| GET | /api/wallets/{address}/projection | `WalletProjection`: his last 30d replayed by the discovery copy-sim onto `allocation_usd` (default 1000) at `trade_direction` / `exposure_mode` / `target_leverage` (unset: the wallet's current terms), with his coin filters. Cached data only, no HL call. 202 `ScoutStatus` + a queued Scout build when nothing is cached, 404 when Scout cannot build him, 409 while a what-if runs |
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
| GET | /api/accounts | `TradingAccount[]` (agent status from extraAgents, cached 10 min) |
| POST | /api/accounts/create | `CreateAccountRequest` -> `CreateAccountResponse` (main key returned ONCE). Agent approval fails on an unfunded wallet: account kept, status `missing`, `backup_warning` says fund it then Refresh agent |
| POST | /api/accounts/import-key | `ImportApiKeyRequest` -> `TradingAccount`. 400: the key is the main key, or not an approved agent of that address (extraAgents) |
| GET / POST | /api/accounts/import-env | `{available, address, reason}` / -> `TradingAccount[]`: imports `.env` as "Main (from .env)" and activates it if nothing is active (404 when `.env` has no pair) |
| POST | /api/accounts/approve/prepare | `AgentApprovalPrepareRequest` -> `{typed_data, action, nonce}` for eth_signTypedData_v4 (chainId 0xa4b1 mainnet / 0x66eee testnet) |
| POST | /api/accounts/approve/submit | `AgentApprovalSubmitRequest` -> `TradingAccount`. 400 wrong signer / tampered action / stale nonce, 409 unfunded wallet, 502 HL rejected |
| POST | /api/accounts/{id}/activate?force= | -> `TradingAccount`. 409 while the current active account still has engine copies (they would stop being managed) unless `force=true` |
| PATCH / DELETE | /api/accounts/{id} | `{label}` -> `TradingAccount` / `{ok}`. Deleting the active account stops trading |
| POST | /api/accounts/{id}/refresh-agent | `{passphrase?}` -> `TradingAccount`; 401 wrong passphrase, 409 connected accounts ("re-run sign-in") |
| POST | /api/accounts/transfer | `TransferRequest` -> `{ok, from_address, to_address, amount_usd}`: usdSend from a created account to another vault account, capped by live perps withdrawable (502 if unread); 401 wrong passphrase |
| GET | /api/accounts/{id}/funding-info | `FundingInfo`: network, Arbitrum chain id, native USDC, Hyperliquid bridge, `min_deposit_usd` 5, `withdraw_fee_usd` 1, `signer` browser/passphrase, live `limits` (null if the read failed), notes |
| POST | /api/accounts/{id}/action/prepare | `UserActionPrepareRequest` -> `{typed_data, action, nonce}` for usd_class_transfer / usd_send / withdraw (guards checked: amount > 0 and <= live limit, withdraw > fee, withdraw to another address needs `confirm_destination`, usdSend only to another vault account, no move on unified accounts) |
| POST | /api/accounts/{id}/action/submit | `UserActionSubmitRequest` -> `UserActionResult`. Guards re-checked, signer must be the account address (400), posted to /exchange (502 HL rejected). Rate-limited per kind |
| POST | /api/accounts/{id}/action | `UserActionRunRequest` (passphrase, created accounts) -> `UserActionResult`; 401 wrong passphrase. Rate-limited per kind. Every attempt is a line in `data/vault/audit.jsonl` (no secrets) |
| GET | /api/accounts/{id}/summary | `AccountSummary` (balances, exposure, curves from hl; metrics from `discovery.scout.public.account_metrics` when it exists, else null) |
| GET | /api/accounts/{id}/history?kind= | `{kind, rows}`, kind fills / orders / transfers / balances (row shapes in `services/api/api/account_history.py`) |
| GET | /api/market/candles?coin=&interval=&start_ms=&end_ms= | bars `{t_ms,o,h,l,c,v}[]` via `discovery.public.candles`; interval in 1m..1d (HL set), end > start, at most 5000 bars, else 422 |

## Processes, data files, HL rate budget
- `data/` must be the same absolute path for every process (`python -m api` / `python -m engine`
  resolve `COPYCAT_DATA_DIR` to an absolute path at startup).
- Files: `settings.json` (api writes), `engine-<address>.db` (one per trading account; a pre-v6
  `engine.db` is renamed by its owner) + `engine_status.json` (last cycle, any account) +
  `engine_account.json` (account the last cycle ran for) + `events.jsonl` (engine writes),
  `vault/` (services/vault, written by the api, read by the engine and `hl`), `discovery.db`,
  `close_all.flag` (api writes, engine deletes), `stop/<address>.flag` (api writes, engine deletes once
  that wallet is stopped), `api_token` (api), `engine.lock` (flock held by the one
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
Trading accounts live in `services/vault` (`data/vault/`). Each has a main
address (holds the money) and an agent ("API") key that signs orders: it can
trade, it cannot withdraw. Add one from the web: create a wallet (copycat
keeps its main key, sealed with your passphrase), sign in with a browser wallet
(approveAgent), or paste an API wallet key approved at app.hyperliquid.xyz/API.
The engine trades the ACTIVE account; `hl.env` and the engine re-resolve it
every write / cycle. Before any account has been activated, `.env`
(`COPYCAT_ACCOUNT_ADDRESS` + `COPYCAT_AGENT_KEY`) still trades; the web's
"Import from .env" moves that pair into the vault. After the first activation
the vault decides and never falls back to `.env`. A main wallet's key is never
accepted as an agent key. Switching accounts gives the new one a clean engine
book; the old account's copies are no longer managed (activate refuses while
they exist unless forced).

## Running
`docker compose up` runs api, engine worker, scout scheduler, web. `make dev` runs them locally.
`make test` runs every service's gate tests (<2s each, no network).
`make eval` runs the live read-only evals (engine dry-run against real leaders,
discovery smoke run).
