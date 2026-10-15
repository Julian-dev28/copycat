# services/api

FastAPI over HTTP/JSON for the web UI. Owns `data/settings.json` (the only
writer) and the bearer token. Never signs orders. Account administration
(`/api/accounts`) goes through `services/vault`, which signs agent approvals and
transfers with a created wallet's main key; secrets pass through a request and
are dropped.

    COPYCAT_SKIP_DOTENV=1 .venv/bin/python -m api      # binds COPYCAT_BIND:COPYCAT_API_PORT
    .venv/bin/python -m pytest services/api            # gate, <1s
    .venv/bin/python -m api.openapi_export             # regenerate openapi.json (gate checks it)

## Routes (prefix /api)

| method | path | notes |
|---|---|---|
| GET | /health | `{ok, version}`, no auth |
| GET / PUT / PATCH | /settings | `Settings`. PATCH semantics below |
| POST | /leaders | `{address}`; 400 bad address or our own account, 409 at 25 leaders |
| DELETE | /leaders/{address} | also drops its override; idempotent |
| POST | /wallets/{address}/copy | `WalletCopyRequest` -> `Settings`; invest or adjust (see Trade page) |
| POST | /wallets/{address}/preview | `WalletCopyRequest` -> `WalletPreview`; 502 their read failed, 503 engine missing |
| POST | /wallets/{address}/stop | `WalletStopRequest` -> `{settings, stopping}`; 404 not in book and no copies |
| GET | /wallets | `WalletPosition[]`: book wallets, then stopped ones (winding down or with PnL history); `?include=archived` adds archived |
| POST | /wallets/{address}/pause | -> `Settings`; no new opens/adds, exits mirrored; 404 not in book |
| POST | /wallets/{address}/resume | -> `Settings`; 404 not in book |
| POST | /wallets/{address}/archive | -> `WalletPosition`; stopped wallets only (409 otherwise) |
| GET | /wallets/{address}/events | `EngineEvent[]` of that wallet, newest first; `limit`, `before_ms` |
| GET | /wallets/{address}/projection | `WalletProjection` from cached data; 202 while Scout builds them |
| GET | /status | `EngineStatus` from `engine.public.status()`; 503 if the engine package is missing |
| GET | /events?limit=&since_ms= | newest first |
| GET | /events/stream | SSE, tails `data/events.jsonl` from its end, one `EngineEvent` JSON per message |
| POST | /engine/halt | `enabled=false`; exits keep mirroring |
| POST | /engine/close-all | `enabled=false`, then writes `data/close_all.flag`; returns `{requested_ms, pending, settings}`. The engine's next cycle closes every copy |
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
| GET | /accounts | `TradingAccount[]` |
| POST | /accounts/create, /accounts/import-key, /accounts/approve/prepare, /accounts/approve/submit | add an account (see docs/ARCHITECTURE.md) |
| GET / POST | /accounts/import-env | `.env` migration status / import |
| POST | /accounts/{id}/activate?force=, /accounts/{id}/refresh-agent, /accounts/transfer | |
| PATCH / DELETE | /accounts/{id} | rename / remove |
| GET | /accounts/{id}/summary, /accounts/{id}/history?kind= | `AccountSummary`, `{kind, rows}` |
| GET | /accounts/{id}/funding-info | `FundingInfo` (bridge, USDC, min deposit, withdraw fee, live limits) |
| POST | /accounts/{id}/action/prepare, /accounts/{id}/action/submit, /accounts/{id}/action | spot<->perps, usdSend, withdraw3 (browser-signed / passphrase) -> `UserActionResult` |
| GET | /market/candles?coin=&interval=&start_ms=&end_ms= | candle bars, <= 5000, 422 on bad interval/range |
| POST | /mcp/plans | `CopyPlanRequest` -> `CopyPlan` (read-only on the book; stored 120 s) |
| POST | /mcp/plans/{plan_id}/execute | `{confirm_code}` -> `CopyPlanResult`; 403 off / bad code / over cap, 404, 409 their book changed / book full, 410 used / expired, 429 |

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

The one-off discovery run (`python -m discovery`, services/discovery/README.md)
has no HTTP surface any more: `/api/discovery/runs*` and `api.discovery_client`
went with the Discover page (v16; Scout is the board). The thesis fingerprint
child (`api.thesis_client`) keeps the same recipe: `COPYCAT_HL_PRIORITY=background`,
absolute data dir, no agent key, result over a pipe.

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

## Trade page (wallets)

Routes in `api/routes/wallets.py`. Every wallet route needs the bearer token.

- **copy** (`SettingsStore.copy_wallet`), `settings_source` global: one
  flock'd write adds the wallet if new and clears its override down to
  `{invested_ms}` (bookkeeping for the PnL ledger; nothing sizes from it), so
  the wallet runs on the Settings tab exactly. `settings_source` custom
  (default; `allocation_usd` required, else 422): one flock'd write adds the
  wallet if new (409 at `MAX_LEADERS`, 400 bad/own address) and sets
  `leader_overrides[address]` to `sizing_mode: allocation` plus the ticket's
  `allocation_usd`, `exposure_mode`, `target_leverage`, and, when given,
  `margin_mode`, `max_worse_entry_pct`, `small_account_mode`, `leverage_mode`,
  `leverage`, `only_new_positions`. Other fields of an existing override are
  kept. `invested_ms` is now for a new wallet (or one without it); a re-post
  or a global/custom switch keeps it (the PnL ledger is not reset). Target exposure without `target_leverage` is 422.
  A pending stop flag for the wallet is deleted (newer command wins).
- **preview** (global: the book-wide settings via `engine.sizing.plan_copy`,
  per-position sizes in fixed_margin / fixed_notional / proportional; custom:
  `plan_allocation`; `only_new_positions` on a new wallet previews nothing
  copied now): `engine.public.preview_wallet` via `RealEngineClient.preview`
  (lazy import, flips the process to background HL priority first). It is
  `engine.sizing.plan_allocation` on live reads, the same function the engine
  sizes with, so the ticket shows what the engine will do: per position the
  slice, leverage, margin, status (copy / trimmed / bump / skip + reason),
  liquidity cap and `fill_cycles`; plus `min_allocation_for_full_book` and
  notes (e.g. not enough free margin). Our existing copies of them count
  against the allocation cap, so a bigger re-post previews the adjust.
- **stop** (`SettingsStore.stop_wallet` + `api/wallet_stop.py`): removes the
  wallet and its override, then writes `data/stop/<address>.flag`
  `{close_positions, requested_ms}` atomically. 404 when the wallet is neither
  in the book nor an orphan the engine still holds copies of (503 if the
  engine status cannot be read to check). `stopping` is true for a pending
  stop-and-close.
- **list**: one `WalletPosition` per book wallet (settings order), then every
  orphan with open copies or a pending stop. Position fields are the
  engine's `LeaderStatus` from its last cycle; `pnl_usd` = realized +
  unrealized, `roe_pct` = pnl / `allocation_usd` x 100 (None off allocation
  sizing). `settings_source`: global when the wallet has no override beyond
  `invested_ms`, else custom (winding-down rows: custom if they ran on
  allocation terms). Terms come from settings for book wallets and from the engine's
  `effective` (the terms it last ran with) for winding-down ones. If the
  engine package is missing the book rows still come back, zeroed.

- **v8 copy fields** (custom only): `trade_direction` (copy | counter),
  `coin_allowlist`, `coin_blocklist` go into the override when given; lists
  are stripped and de-duplicated case-insensitively (`clean_coins`), and []
  is a real value ("no list of its own", replacing the book-wide list).
  `paused` is never touched by copy: a re-post of a paused wallet stays paused.
- **pause / resume** (`SettingsStore.set_paused`): sets the override's
  `paused`. A wallet with no override gets `{paused: true}`; resume sets it
  back to None (inherit), or `false` when the book-wide `paused` is on, and
  drops an override left empty. `settings_source` ignores `invested_ms` and
  `paused`, so a paused global wallet is still "global".
- **status** (`wallet_status`): stopping (stop flag pending, or the engine
  says a close is retrying) > in the book: paused (effective `paused`) or
  running > out of the book: archived (ledger `archived_ms`, no copies) or
  stopped. A stopped wallet stays listed while it has copies or a ledger row
  (its PnL history) until it is archived.
- **archive**: 409 for a wallet in the book, still stopping, or with copies
  (the engine's status row, and `engine.public.archive_wallet` re-checks its
  own copy rows: `ArchiveRefused`). Writes `archived_ms` into the engine
  ledger of the active account; the engine then stops reading that wallet
  (it keeps reading any wallet that still holds a copy). A later copy sets a
  new `invested_ms`, which un-archives it.
- **events**: `engine.public.leader_events` reads `events.jsonl` backwards
  from the end in 64KB blocks, stops at `limit` matches or 8MB scanned.
  Skip events carry their leader since v8, so a wallet's history shows
  "paused", "filtered: BTC", "worse than entry" and the like.
- **projection**: the Scout what-if (`scout.what_if`, cached fills and
  candles only, same `scout_what_if_lock` as the trader file) with the
  override `{sizing_mode: allocation, allocation_usd, trade_direction,
  exposure_mode, target_leverage}` on the wallet's current effective
  settings and `sim_equity_usd = allocation_usd`. `LookupError` (no stats
  cached) -> `scout.profile` queues the build and the route answers 202 with
  its `ScoutStatus`. `skipped` is the sim's under-minimum count.
- **style**: one `scout.page({"q": address, "limit": 1})` per wallet,
  cached 5 minutes on the app; never raises, never queues a build.

`PATCH /settings` also accepts the v5 book-wide fields (`allocation_usd`,
`exposure_mode`, `target_leverage`, `invested_ms`, `small_account_mode`,
`max_order_volume_pct`, `max_slippage_pct`) and the v8 ones
(`trade_direction`, `coin_allowlist`, `coin_blocklist`, `paused`).

## MCP copy plans (`/api/mcp`, contract v9)

`api/mcp_plans.py` (guards, store, warnings) and `api/routes/mcp_plans.py`.
The copycat MCP server's `copy_plan` / `execute_copy_plan`. A plan is the
engine preview at custom terms (allocation = amount; leverage L: exposure
target L, unset: exposure match + leverage_mode match; `max_worse_entry_pct` =
the entry deviation; `only_new_positions` false; `one_shot` = not follow), the
cached projection, warnings (execution off, over cap, over max leverage, own
account, full book, already in the book / paused, trading not live, algo or
scalp style, their liquidation < 5%, copies above 20x, slices under the minimum,
no projection) and a sha256 of their positions (coin, side, size x entry).

Execute guards, in order: (a) `COPYCAT_MCP_ALLOW_TRADING=1` in the api env
(403 with how to enable); rate limit 10/hour counted from the audit log (429);
(b) unknown plan 404, used or expired 410; (c) constant-time confirm code, 403,
the 3rd wrong code voids the plan; (d) `amount_usd <= COPYCAT_MCP_MAX_USD`
(default 100) and leverage <= `max_position_leverage`, 403; (e) their positions
still hash to `book_fingerprint`, else 409 and the plan is void; (f) room in
the book, 409. Then `SettingsStore.copy_wallet` + `clear_stop`, exactly like
POST /wallets/{a}/copy. `enabled` / `dry_run` are never written. The whole
check-and-write runs under the plan store's flock, so a plan executes once.

Files: `data/mcp_plans.json` (0600, atomic, pruned 10 min after expiry),
`data/mcp_audit.jsonl` (0600, append; terms and outcomes only, never the code
or the token). Env vars are read per request, so tests monkeypatch them and a
change needs an api restart only when it comes from `.env`.

## Trading accounts (`/api/accounts`)

Routes in `api/routes/accounts_onboard.py` (adding) and `api/routes/accounts.py`
(managing, summary, history), both behind `require_auth`. Vault errors map to
their `http_status` (400 invalid, 401 wrong passphrase with the single detail
"invalid passphrase", 404 unknown id, 409 fund first / re-run sign-in / open
copies, 502 HL). Secret-bearing routes (create, import-key, import-env, submit,
refresh-agent, transfer, funding submit/run) are rate-limited in process: 5/min and 30/hour per
route (`api/attempt_limit.py`), 429 beyond. A 422 on `/api/accounts/*` never
echoes the request input (FastAPI's default would echo a pasted key). No route
logs a body.

`import-env` reads the key from `COPYCAT_ENV_FILE` (compose mounts the host
`.env` there read-only), else `./.env` unless `COPYCAT_SKIP_DOTENV=1`.

Summary metrics: balances, exposure, leverage, margin usage and the pnl/value
curves come from hl reads here (`api/account_summary.py`). Risk, trades, style,
tiers, win streak and daily pnl need `discovery.scout.public.account_metrics(address)
-> dict` (keys = those `AccountSummary` field names), which discovery does not
expose yet; until it does they are null. `copytrade_usd` = sum of
`LeaderStatus.margin_used_usd` in that account's own engine snapshot.

### Funding (`api/routes/accounts_funding.py`, `api/funding.py`)

- `GET .../funding-info`: static facts from `hl.accounts.funding_info()` (Arbitrum
  chain id, native USDC, Hyperliquid bridge, 5 USDC minimum, $1 withdraw fee, the doc
  URL they were verified against) plus live `limits` from `account_state` +
  `spotClearinghouseState` (`null` when a read fails; the facts still come back).
- Limits: usdSend / withdraw3 / perps->spot are capped by the main perp dex's
  `withdrawable` (unified accounts: spot USDC free, as hl.venue reports it);
  spot->perps by spot USDC total - hold. Unified accounts refuse a move (one balance).
- `action/prepare` -> exact action + EIP-712 typed data; `action/submit` -> the vault
  re-checks every guard, recovers the signer (must be the account address) and
  posts. `POST .../action` is the passphrase path for created accounts.
- Every money route reads the limits first (502 if it cannot), submit and the
  passphrase route are rate-limited per kind (`action-<kind>` buckets, 5/min, 30/h).
  `/accounts/transfer` now uses the same guards (perps withdrawable cap) and audit.
- Withdraw destination defaults to the account itself; any other address needs
  `confirm_destination` equal to it. usdSend only goes to another vault account.
- The MCP server never calls any `/api/accounts` route (its test forbids it).

Tests: `tests/test_accounts_funding.py` (facts, limits, unified, browser round trip,
signer mismatch, bounds, confirm, rate limit, no passphrase/signature in logs or the
audit file). `tests/test_accounts_onboard.py`, `tests/test_accounts_manage.py` run the
real vault in a temp dir with a fake HL (`tests/accounts_fakes.py`) and assert
no key or passphrase appears in any response or captured log.
