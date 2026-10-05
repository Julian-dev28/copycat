# services/hl

Every Hyperliquid call copycat makes lives here. Public surface: `hl.HlVenue`,
implementing `contracts.venue.Venue` exactly. The engine and discovery
services never talk to Hyperliquid directly or import anything from this
package except that one class and the pure parser `hl.leaderboard.parse_rows`.

```python
from hl import HlVenue
venue = HlVenue()
state = venue.account_state("0x...")   # None on failure, never raises
```

## Files

| file | owns |
|---|---|
| `hl/venue.py` | `HlVenue` -- the contract surface, all 17 `Venue` methods (contract v5) |
| `hl/leaderboard.py` | `parse_rows`: pure, string-numbers -> typed leaderboard rows (no network) |
| `hl/env.py` | network selection (`COPYCAT_NETWORK`), credentials, timeout |
| `hl/http.py` | shared session, the timeout guard, `http_post` (every read goes through this) |
| `hl/rate_limit.py` | cross-process file-backed token bucket with engine priority, in-process fallback, the documented per-endpoint weight table |
| `hl/meta.py` | per-dex perp-universe cache, HIP-3 dex-list cache, spot-price cache, per-dex asset-ctx cache (`asset_stats`), 2s `l2_book` cache, `max_leverage`, `is_isolated_only` |
| `hl/sizing.py` | pure price/size rounding math (no network) |
| `hl/sdk.py` | lazy `hyperliquid.exchange.Exchange` (writes only), timeout-guarded, refuses the main wallet's key, rebuilt when the active credentials change (cache key: agent address, account, base url) |
| `hl/accounts.py` | account admin for services/vault: approveAgent typed data / signing (SDK `sign_agent`), usdSend signing, funding (`FUNDING` bridge/USDC per network, verified against HL's docs; `user_action` / `user_action_typed_data` / `sign_user_action` for usdClassTransfer, usdSend, withdraw3 with the SDK's own field lists and sign_* functions), `post_signed_action` (POST /exchange, never raises, never logs the body), `extra_agents` |
| `hl/history.py` | Account page reads: `historical_orders`, `ledger_updates`, `spot_balances` (None on failure) |

Ported from `pathiel` at commit `ab2e800` (`client/exchange.py`,
`client/http_session.py`, `client/hl_client.py`,
`agents/copycat_live.py::LiveVenue`, `agents/executor.py::close_position_market`),
stripped of pathiel-specific state files, memory, and logging setup.

## The contract

### Reads: None/0.0 on failure, never raise

Every read method returns `None` (for a structured result) or `0.0`
(`mid`) / `0` (`max_leverage`) on ANY failure -- a bad response shape, a
timeout, a rate-budget skip. Every failure is logged. Nothing in this
package raises into a caller; `account_state`, `extras`, and `fills` each
wrap their whole body in a defensive `try/except` on top of per-call
guards, because a failed read must never look like a flat leader or zero
equity (that's the one rule this whole package exists to protect).

`max_leverage(coin) -> int` deserves its own callout: it returns `0` on
failure, **never silently `1`**. A caller doing `min(requested, max_leverage(coin))`
would otherwise quietly mis-size every position to 1x leverage on a
transient meta-cache miss -- this is the exact bug that bit pathiel on
2026-09-08 (two positions opened at 1x when the config said 3x, because a
partially-warmed cache was missing `maxLeverage` and the old code fell
back to 1 instead of forcing a refresh). `is_isolated_only` and `mid` do
the opposite on purpose: `is_isolated_only` defaults to `False` (cross) so
an outage doesn't force every coin into isolated margin, and `mid` is
`0.0` because there's no leverage-style silent-wrong-default risk there.

### Writes: no key, no call

`set_leverage`, `market`, and `close` all check
`COPYCAT_AGENT_KEY` + `COPYCAT_ACCOUNT_ADDRESS` before touching the SDK.
Missing either one returns `{"ok": False, "error": "COPYCAT_AGENT_KEY/COPYCAT_ACCOUNT_ADDRESS not set"}`
immediately -- no network call, no exception.

**Main wallet key refused.** If `COPYCAT_AGENT_KEY` derives to
`COPYCAT_ACCOUNT_ADDRESS`, the main wallet's own private key was pasted.
That key can withdraw; copycat never uses it. `sdk.get_exchange` raises
`MainWalletKeyError` and every write returns `ok False` with an error
telling the user to create an API wallet at `app.hyperliquid.xyz/API`.

`set_leverage` is **strict**: `ok` is only `True` when HL's response body
says `status == "ok"`. `exchange.update_leverage` can return HTTP 200 with
`{"status": "err", "response": "<message>"}`, and a non-strict caller
("the SDK call didn't raise") would read that as success.

An isolated-only market (most HIP-3 coins, ~3% of native HL) rejects a
cross-margin request; `set_leverage` detects this via `is_isolated_only`
and falls back to isolated rather than sending a call it knows will no-op.

### `market(coin, is_buy, size, mid, reduce_only=False, cloid=None, max_slippage_pct=1.0)`

IOC limit order. Rules, each with a regression test in
`tests/test_venue_writes.py`:

| rule | behavior |
|---|---|
| cloid | `0x` + 32 hex, sent as `Cloid.from_str(cloid)`. Malformed: `ok False`, nothing sent. |
| full vs partial | `ok True` only when HL's `filled.totalSz` >= the sent size (within half a size tick). Partial: `ok False`, `error "partial fill a/b"`, `filled_sz`/`avg_px` set. `filled_sz` is set whenever HL reported a fill. |
| ambiguous | the `/exchange` POST raised a timeout, connection error, or 5xx (`requests` Timeout/ConnectionError, `TimeoutError`, SDK `ServerError`): `{ok False, ambiguous True, error}`. The order may be live; resolve with `order_status(cloid)` or a fresh `account_state`. A clean HL rejection (`{"error": ...}` status, `status: err`, a 4xx `ClientError`) or a failure before sending is `ambiguous False`. HL `ok` with no statuses is ambiguous. |
| slippage cap | limit = `mid * (1 +/- max_slippage_pct/100)`, rounded INSIDE the cap (buy down, sell up). If the l2Book touch (best ask for a buy, best bid for a sell) is already past the cap: `{ok False, error "slippage cap"}`, nothing sent. No book (read failed): sent at the cap. |
| $10 floor | opens are bumped to $10.50 (`sizing.order_size`); `reduce_only` orders are **never** bumped. A size that rounds to 0 is refused. |

### `order_status(cloid)`

`POST /info {"type": "orderStatus", "user": COPYCAT_ACCOUNT_ADDRESS, "oid": "<cloid hex>"}`.
HL accepts the cloid string in the `oid` field (the SDK's
`Info.query_order_by_cloid` sends exactly this). Mapping:

| HL | returned |
|---|---|
| `{"status": "unknownOid"}` | `"unknown"` |
| `open`, `filled`, `triggered` | same |
| `canceled`, `scheduledCancel`, any `...Canceled` (`marginCanceled`, `reduceOnlyCanceled`, ...) | `"canceled"` |
| `rejected`, any `...Rejected` (`minTradeNtlRejected`, `iocCancelRejected`, ...) | `"rejected"` |
| read failed, bad shape, no account, malformed cloid | `None` |

An IOC that filled part of its size and cancelled the rest reports
`canceled`: **`canceled` does not mean zero fill**. Take the real size
from `account_state`.

### `close(coin, cloid=None)`

Reduce-only IOC sized from a fresh `account_state` read of our own
position (never a caller size), then a **second fresh read**: `ok True`
only if the position is now flat. Partial fill, slippage cap, rejection,
or a fill the read disagrees with: `ok False` with `filled_sz`. Post-order
read failed: `ok False`, the order's `filled_sz`/`ambiguous` kept. An
ambiguous order that the fresh read shows flat is `ok True`. Retrying is
always safe: each call re-reads its size and reduce-only cannot flip.
Slippage cap for closes: `COPYCAT_HL_CLOSE_SLIPPAGE_PCT` (default 1.0).

### Timeouts on the SDK

`Exchange(..., timeout=COPYCAT_HL_TIMEOUT_S)` (default 10s): the SDK's
`Exchange.__init__` builds an `Info` that reads `spotMeta`, `perpDexs`
and one `meta` per dex inside the constructor, all bounded by that
timeout. Both the Exchange's and its Info's sessions then get the
`timeout None -> default` guard. The singleton lock is never held across
construction; two cold-start racers may both build one, the first stored
wins.

## Keys and network

`.env` (see `.env.example` at the repo root):

```
COPYCAT_ACCOUNT_ADDRESS=0x...   # your main wallet -- holds the funds
COPYCAT_AGENT_KEY=0x...         # the agent ("API") wallet's private key -- signs, cannot withdraw
COPYCAT_NETWORK=mainnet         # mainnet | testnet
```

Credentials resolve through `hl.env.credentials()`: the vault's active account
(services/vault) once the vault is authoritative (an account was activated),
else these env vars. An unreadable vault means no credentials (fail closed).

Approve the agent wallet at `app.hyperliquid.xyz/API`. `COPYCAT_NETWORK`
picks the base URL for every `/info` and `/exchange` call this service
makes (`hl.env.base_url()`), including the leaderboard pull (hits
`stats-data.hyperliquid.xyz/{Mainnet,Testnet}/leaderboard` to match).
Reads work with no keys set at all; only the three write methods need
them.

## Rate limiting

Hyperliquid meters `/info` + `/exchange` requests by a documented weight
and enforces ~1200 weight/min per IP
(`hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits`,
checked 2026-10-02):

| weight | endpoints |
|---|---|
| 2 | `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`, `spotClearinghouseState`, `exchangeStatus` |
| 60 | `userRole` |
| 20 | everything else documented (`meta`, `spotMeta`, `spotMetaAndAssetCtxs`, `metaAndAssetCtxs`, `perpDexs`, `delegatorSummary`, `userFillsByTime`, `candleSnapshot`, ...) |
| +1 per 20 items returned | `userFills`, `userFillsByTime`, `historicalOrders`, `fundingHistory`, and others in the per-item group |
| +1 per 60 items returned | `candleSnapshot` |

The budget is per IP and two copycat processes share it: the engine and
discovery (inside the api process today). `hl.rate_limit.HL_LIMITER` is a
`SharedTokenBucket`: one fcntl-locked file, `$COPYCAT_DATA_DIR/hl_rate.bucket`
(`"<tokens> <wall_ts>"`), that every process on the host draws from.
Capacity 1200, refill 20/s, env-tunable via `COPYCAT_HL_RATE_CAPACITY` /
`COPYCAT_HL_RATE_REFILL_PER_SEC`. The file is created on first acquire,
not at import. Both processes must see the same `COPYCAT_DATA_DIR` (it
defaults to the relative `./data`).

| `COPYCAT_HL_PRIORITY` | may spend |
|---|---|
| `engine` (default) | the whole bucket |
| `background` | only down to a reserve of `COPYCAT_HL_RESERVE_FRAC` (default 0.4) of capacity, then sleeps |

So the engine always finds ~40% of the budget (~480 weight) waiting for
it, however hard discovery is pulling. The process that hosts discovery
sets `COPYCAT_HL_PRIORITY=background` in its environment before importing
`hl`, or calls `hl.rate_limit.set_priority("background")` at startup.

If the file cannot be opened or locked, that process falls back to a
private in-process bucket (logged once): pacing becomes per-process, reads
keep working.

Every call through `http_post` acquires the endpoint's **base** weight
first; a budget that does not free up within `max_wait` makes `http_post`
return `None` (logged) without touching the network. The per-item
surcharge (`userFillsByTime`, `historicalOrders`, `candleSnapshot`, ...)
is charged **after** a successful response, from the real list length
(`rate_limit.item_surcharge` + `HL_LIMITER.charge`), into the same shared
bucket. `charge` never waits: the request already happened, so the bucket
may go into debt (floored at -capacity) and every later `acquire`, in
either process, waits for refill to pay it off. Before this, every fills
page pre-charged the 2000-row cap (120) and every candle read an
estimated count, even when HL returned a handful of rows. A real **429** from HL is
retried inside `http_post`: the shared bucket is drained (so the other
process backs off too), then exponential backoff 1s, 2s, 4s (honoring
`Retry-After`, each sleep capped at 4s), at most 3 retries, each retry
re-acquiring its weight. After that, `None`.

Writes charge weight 1 per order before sending (never blocking an order
for more than 2s on our own estimate). The SDK Exchange constructor's own
reads (once per process) are not metered.

## Fills pagination (`fills`)

`userFillsByTime` returns at most 2000 rows per call and only the 10,000
most recent fills are available at all (HL docs). Verified against
mainnet 2026-10-02: rows come back **oldest-first** (nondecreasing by
`time`), and `startTime`/`endTime` are both inclusive (2026-10-05).

`HlVenue.fills` pages forward by setting the next call's `startTime` to
the previous page's **last row's `time`** (not `+ 1`, and not by
offset, which the API doesn't support). The rows of that last millisecond
are dropped from the full page and re-read whole by the next one, because
HL cuts a page at 2000 rows in the middle of a millisecond: on 0xf5d81a13
(aggregated, 2026-10-05) page 1 held 39 rows at its last ms and a refetch
from that ms returned 49, so a `+ 1` cursor silently lost 10. A full page
whose rows all share one millisecond cannot advance that way and falls
back to `+ 1` (logged). Stops on a short page, or after 50 pages (logged;
safety valve against an API that never shrinks below the cap).

### `aggregate_by_time=True`

Passes HL's `aggregateByTime: true`. HL merges every partial fill of one
order at one millisecond (same `coin`, `oid`, `time`) into one row.
Checked 2026-10-05 on `0xe2823659be02e0f48a4660e4da008b5e1abfdf29` over
30 days: 870 raw fills -> 189 rows, 71 merged from 2-54 partials, and
every merged row matched its raw group:

| field | aggregated value |
|---|---|
| `sz`, `closedPnl`, `fee` | sum of the partials |
| `px` | size-weighted average (VWAP) |
| `startPosition`, `hash`, `tid` | the **first** partial's, so `startPosition + signed sz` is still the true end position |
| `dir` | the first partial's label. A group that flips (`Close Short` partials, then `Short > Long`) comes back as `Close Short` with sz 200 from -100: classify from `startPosition` + `side` + `sz`, never from `dir` (discovery.positions does) |

Spot `Spot Dust Conversion` rows are not returned with aggregation (2 of
191 groups on that wallet). Measured on discovery's candidate set: 64,241
-> 10,746 fills, cold discovery time halved. `discovery.fills_cache`
passes it whenever `venue.fills` accepts the kwarg. Live check:
`tests/test_live.py::test_live_fills_aggregate_by_time_matches_raw`.

## Leaderboard (`leaderboard`)

`GET https://stats-data.hyperliquid.xyz/{Mainnet,Testnet}/leaderboard`.
Real response shape (curled 2026-10-02, Mainnet, 46,953 rows):

```json
{"leaderboardRows": [
  {
    "ethAddress": "0x85ecf584f25db6f146718b86d493e33c5af72052",
    "accountValue": "62330451.1721990108",
    "windowPerformances": [
      ["day",     {"pnl": "310963.157278",      "roi": "0.0055071207", "vlm": "1450003736.8299999237"}],
      ["week",    {"pnl": "2852804.9591829996", "roi": "0.0512880601", "vlm": "9048872792.9899978638"}],
      ["month",   {"pnl": "960491.2623950004",  "roi": "0.014177401",  "vlm": "40991110551.9400100708"}],
      ["allTime", {"pnl": "5486773.7299610004", "roi": "0.0456111172", "vlm": "218905315448.549987793"}]
    ],
    "prize": 0,
    "displayName": null
  }
]}
```

Every number is a **string**, not JSON numeric. `windowPerformances` is a
list of `[label, dict]` pairs, not an object -- index it with
`dict(row["windowPerformances"])`. `leaderboard()` returns the raw rows
unnormalized; `discovery` owns turning this into `contracts.models.TraderScore`.

### `hl.leaderboard.parse_rows(raw) -> List[LeaderboardRow]`

Pure helper (no network) that discovery's Scout pipeline runs on
`leaderboard()`'s output (or the whole `{"leaderboardRows": [...]}` body):

```python
{"address": "0x85ec...2052",          # lowercased
 "display_name": None,                # str, or None for null/""
 "account_value": 62330451.17,
 "day":     {"pnl": 310963.16, "roi": 0.0055, "vlm": 1450003736.83},
 "week":    {...}, "month": {...}, "allTime": {...}}
```

All floats. `roi` is a fraction as HL reports it. A row missing any of the
four windows, with a non-finite/unparseable number, or a malformed address
is **dropped** (count logged), never zero-filled: a zeroed window would
score as a real flat trader. `None`/non-list input -> `[]`, so check
`leaderboard()` for `None` first to tell a failed read from an empty board.
Live (2026-10-04): 47,185 / 47,185 rows parsed.

## Portfolio (`portfolio`)

`POST /info {"type": "portfolio", "user": U}`, weight 20. Returns HL's raw
list of 8 `[window, {accountValueHistory, pnlHistory, vlm}]` pairs, in order
`day, week, month, allTime, perpDay, perpWeek, perpMonth, perpAllTime`
(curled 2026-10-04 for `0xe282...df29`):

```json
[["day", {"accountValueHistory": [[1790975760052, "2420588.4847900001"], ...],
          "pnlHistory":          [[1790975760052, "0.0"], [1790984160003, "71448.243577"], ...],
          "vlm": "265999.99"}],
 ["week", {...}], ["month", {...}], ["allTime", {...}],
 ["perpDay", {...}], ["perpWeek", {...}], ["perpMonth", {...}], ["perpAllTime", {...}]]
```

Timestamps are int ms, every value is a **string**. `pnlHistory` is
cumulative from the window start. Non-`perp` windows include spot. Point
counts vary (13 for day, 89 for allTime on that wallet). `None` on a failed
read or any element that is not a `[str, dict]` pair; `[]` is a valid
answer (never-traded address).

## Open orders (`open_orders`)

`POST /info {"type": "frontendOpenOrders", "user": U, "dex": D}`, weight 20
**per dex**, over main + the dexes from the same per-user active-dex cache
`account_state` uses (cold or stale cache = every dex; `COPYCAT_HL_DEXES`
pins the set). Rows are HL's raw dicts (`coin, side, limitPx, sz, oid,
timestamp, triggerCondition, isTrigger, triggerPx, children,
isPositionTpsl, reduceOnly, orderType, origSz, tif, cloid`) except `coin`,
which becomes `"dex:COIN"` on HIP-3 dexes (never double-prefixed), matching
`account_state` position keys. `None` if any dex read fails: a partial list
must never look like "no orders".

A dex found holding orders is added to the active-dex cache without
resetting the rescan clock, so `account_state` still does its own full
scan on schedule. Known gap: an order on a dex where the user has no
equity, no position, and had no orders at the last scan is seen at the next
full rescan (`COPYCAT_HL_DEX_RESCAN_S`, default 300s), not sooner.

## Extras: illiquid-mark exclusion

`extras(user)` returns `{"spot_other_usd", "staked_hype_usd"}`. One real
leader showed a spot balance that, at its listed mid price, marked out to
roughly a **billion dollars** in a token whose actual 24h pair volume
(`dayNtlVlm`) was a few thousand dollars -- `total * midPx` is a real
float but not a realizable value, and sizing a copy off it would wreck the
leader's effective equity. The rule: if a token's marked value exceeds
**10x its own 24h pair notional volume**, it counts as `0` toward
`spot_other_usd` instead. This is a per-token exclusion, not a failed
read -- the rest of the leader's extras still come through.

Spot prices are read via `spotMetaAndAssetCtxs`, one call, cached 30s
(`hl.meta.spot_prices`). Each price is looked up through the universe
entry's own `index` field into the parallel `ctxs` array -- **not** the
entry's position in the `universe` list (the two are not guaranteed to
line up).

`staked_hype_usd` = `(delegated + undelegated + totalPendingWithdrawal)`
HYPE (via `delegatorSummary`), valued at HYPE's spot mid. If HYPE's own
price is missing from the price table, the whole `extras` read fails
(HYPE always has a USDC market; a missing price means the price table
itself is degraded) rather than silently valuing the stake at 0.

## Market stats and depth (`market_stats`, `depth_usd`)

`market_stats(coin) -> Optional[MarketStats]`: `mark_px`, `mid_px`,
`day_volume_usd` (`dayNtlVlm`), `open_interest_usd` (`openInterest` coins x
`markPx`), `max_leverage`. Built by `hl.meta.asset_stats(dex)` from ONE
`metaAndAssetCtxs` call (weight 20) per dex, cached 30s
(`COPYCAT_HL_ASSET_CTX_TTL_S`); that one call serves every coin on the dex.
`"xyz:TSLA"` reads dex `xyz`; a bare coin reads main. Perp ctxs line up with
`universe` by list position. `midPx` null -> falls back to `markPx`; a coin
with no positive `markPx` is left out. None on a failed/malformed read or a
coin not listed on its dex. Failures are not cached and nothing stale is
served past the TTL.

`depth_usd(coin, is_buy, max_slippage_pct) -> Optional[float]`: sum of
`px * sz` on the asks (buy) or bids (sell) for levels at or inside
`mid * (1 +/- pct/100)`, mid = (best bid + best ask) / 2 from the same book.
`l2Book` (weight 2) per coin, cached 2s (`COPYCAT_HL_L2_BOOK_TTL_S`), so the
buy and sell reads of one coin share a fetch. `0.0` = nothing in the band
(e.g. band tighter than the half-spread). None on a failed read, a
one-sided book, or a negative pct. Limit: HL returns at most 20 levels a
side, so a wide band on a deep book under-counts.

## Dex coverage (`account_state`)

pathiel's old `LiveVenue.leader_state` only read the main dex plus a
hardcoded `"xyz"`. `account_state` reads main + **every** registered HIP-3
perp dex, resolved once per day via `perpDexs` and cached
(`hl.meta.perp_dexs`, `hl.meta.dex_list`) -- as of 2026-10-02 that's 10
dexes (`xyz, flx, vntl, hyna, km, abcd, cash, para, mkts, io`), not one.
Configurable via `COPYCAT_HL_DEXES` (comma-separated, `""` = main) for
ops/local tuning, or by passing `override=[...]` to `hl.meta.dex_list`
directly.

## Account abstraction (`account_state`)

`account_state` also reads `{"type": "userAbstraction", "user": U}`. The
response is a bare JSON string (curled 2026-10-04:
`0xe2823659be02e0f48a4660e4da008b5e1abfdf29` -> `"unifiedAccount"`,
`0x2c2e4efF574B3Fd9879AdeF9c5CAC6fD7C916985` -> `"disabled"`; other
values: `"portfolioMargin"`, `"default"`, `"dexAbstraction"`). The raw
value goes in `state["abstraction"]`, cached per user for 10 min
(`COPYCAT_HL_ABSTRACTION_TTL_S`). A failed read serves the last value
seen, or omits the key if none; it never fails `account_state`.

Under `unifiedAccount` / `portfolioMargin` one spot balance collateralizes
every perp dex and per-dex `withdrawable` is meaningless (measured live:
$5.7k reported vs $844k actually free). In those modes `available[dex]`
is set, for every dex read, to spot USDC `total - hold` from
`spotClearinghouseState`. Other modes keep per-dex `withdrawable`.

## Meta caching

Per-dex perp universes (`hl.meta.universe`) cache for 1h
(`COPYCAT_HL_META_TTL_S`); the HIP-3 dex list (`hl.meta.perp_dexs`) caches
for 24h (`COPYCAT_HL_DEX_LIST_TTL_S`); spot prices
(`hl.meta.spot_prices`) cache for 30s (`COPYCAT_HL_SPOT_PRICE_TTL_S`). Every
universe/dex-list cache serves its last-known-good value on a fetch
failure rather than an empty result -- a transient API blip must never
blank coin resolution mid-cycle. Market stats (`hl.meta.asset_stats`, 30s,
`COPYCAT_HL_ASSET_CTX_TTL_S`) and books (`hl.meta.l2_book`, 2s,
`COPYCAT_HL_L2_BOOK_TTL_S`) return None on failure instead: stale prices
are worse than no price.

## Testing

```
.venv/bin/python -m pytest services/hl/tests          # gate: <2s, no network
.venv/bin/python -m pytest services/hl/tests -m live   # live eval: hits the real API
```

Gate tests (250, ~0.4s) fake `http_post` and the SDK `Exchange` -- no
network (conftest replaces the HTTP session with one that refuses every
POST, so an unfaked read cannot leak to mainnet), deterministic (one test spawns a real child Python process to
prove the rate-limit file is shared across processes). They cover:
price/size rounding (incl. HL's 5-sig-fig rule below $1, IOC-direction
rounding, the integer-size-coin floor, reduce-only never bumped), the
never-silently-1 `max_leverage` forced-refresh path, `is_isolated_only`'s
default-False fallback, the timeout guard (including the exact SDK bug --
`timeout=None` passed explicitly, so `setdefault` can't catch it) on both
the Exchange and its internal Info, the shared token bucket (shared
budget, background reserve, drain, corrupt file, fallback) and 429
backoff, `account_state`'s multi-dex aggregation and HIP-3 coin
namespacing, `extras`'s index-based spot pricing and the illiquid-mark
exclusion, `fills` pagination, `leaderboard`/`candles` parsing,
`userAbstraction` (unified vs standard `available`, failure, cache),
`set_leverage`'s strict-error-body check and isolated-only fallback, and
contract v2 writes (`tests/test_venue_writes.py`): cloid passthrough,
`order_status` mapping, full vs partial fills, ambiguous vs clean
failures, the slippage cap, `close` confirmed by a fresh read, the
main-wallet-key guard, and the no-key write refusal. Contract v3
(`tests/test_venue_scout.py`): `portfolio` raw passthrough + bad-shape and
failure paths, `open_orders` multi-dex aggregation, HIP-3 namespacing,
active-dex cache reuse, any-dex-fails -> None, and `parse_rows` typing and
malformed-row dropping. Contract v5 (`tests/test_venue_market.py`):
`market_stats` field mapping, HIP-3 dex routing, one call per dex across
coins, TTL expiry, mid->mark fallback, unknown coin / malformed read ->
None, failures not cached; `depth_usd` band math both sides (inclusive
bound, band inside spread = 0, one-sided book = None), per-coin 2s book
cache, failure paths.

`test_live.py` (13 tests, `@pytest.mark.live`, excluded from the default
gate by `pyproject.toml`'s `addopts = "-m 'not live'"`) hits the real
Hyperliquid mainnet API against `0xe2823659be02e0f48a4660e4da008b5e1abfdf29`
and asserts shape/sanity, not exact numbers (real balances move). Last run
(2026-10-02): `account_state` equity_perp_usd=$454,419.02 across 10 open
positions including a HIP-3 `xyz:TSLA` position; `extras`
spot_other_usd=$13.49, staked_hype_usd=$90,471.03; 128 fills in the last
24h; leaderboard 46,953 rows; `mid(BTC)`=$84,862.50; `max_leverage(BTC)`=40.
Run 2026-10-04 (all 9 green): `portfolio` 8 windows, allTime 89 points;
`open_orders` 3 resting orders (BTC, ETH, GMX); `parse_rows` 47,185/47,185.
Run 2026-10-04 (v5, 4 new green): `market_stats(BTC)` mark $85,030, vol
$501.7M, OI $3.20B, 40x; `market_stats(xyz:TSLA)` mark $371.41, vol $879k,
OI $50.1M, 20x; `depth_usd` at 1%: BTC buy $3.64M / sell $7.17M, xyz:TSLA
buy $120k / sell $138k.
