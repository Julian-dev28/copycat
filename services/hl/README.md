# services/hl

Every Hyperliquid call copycat makes lives here. Public surface: `hl.HlVenue`,
implementing `contracts.venue.Venue` exactly. The engine and discovery
services never talk to Hyperliquid directly or import anything from this
package except that one class.

```python
from hl import HlVenue
venue = HlVenue()
state = venue.account_state("0x...")   # None on failure, never raises
```

## Files

| file | owns |
|---|---|
| `hl/venue.py` | `HlVenue` -- the contract surface, all 12 `Venue` methods |
| `hl/env.py` | network selection (`COPYCAT_NETWORK`), credentials, timeout |
| `hl/http.py` | shared session, the timeout guard, `http_post` (every read goes through this) |
| `hl/rate_limit.py` | token-bucket limiter + the documented per-endpoint weight table |
| `hl/meta.py` | per-dex perp-universe cache, HIP-3 dex-list cache, spot-price cache, `max_leverage`, `is_isolated_only` |
| `hl/sizing.py` | pure price/size rounding math (no network) |
| `hl/sdk.py` | lazy `hyperliquid.exchange.Exchange` singleton, used only for writes |

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

`set_leverage` is **strict**: `ok` is only `True` when HL's response body
says `status == "ok"`. `exchange.update_leverage` can return HTTP 200 with
`{"status": "err", "response": "<message>"}`, and a non-strict caller
("the SDK call didn't raise") would read that as success.

An isolated-only market (most HIP-3 coins, ~3% of native HL) rejects a
cross-margin request; `set_leverage` detects this via `is_isolated_only`
and falls back to isolated rather than sending a call it knows will no-op.

`close(coin)` reads the account's own live position size via
`account_state` and closes exactly that -- it never trusts a caller-
supplied size, because the $10-minimum-order floor in `market()` would
otherwise overshoot a sub-$10 residual and flip it to the opposite side.

## Keys and network

`.env` (see `.env.example` at the repo root):

```
COPYCAT_ACCOUNT_ADDRESS=0x...   # your main wallet -- holds the funds
COPYCAT_AGENT_KEY=0x...         # the agent ("API") wallet's private key -- signs, cannot withdraw
COPYCAT_NETWORK=mainnet         # mainnet | testnet
```

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

`hl.rate_limit.HL_LIMITER` is a single process-wide token bucket, capacity
1200, refill 20/s (= 1200/min), env-tunable via `COPYCAT_HL_RATE_CAPACITY`
/ `COPYCAT_HL_RATE_REFILL_PER_SEC`. Every call through `http_post`
acquires its estimated weight first; a drained bucket makes `http_post`
return `None` (logged) without ever touching the network, rather than
firing into a real 429.

## Fills pagination (`fills`)

`userFillsByTime` returns at most 2000 fills per call and only the 10,000
most recent fills are available at all (HL docs). Verified against
mainnet 2026-10-02: fills come back **oldest-first** (strictly
nondecreasing by `time`) within the requested window. `HlVenue.fills`
pages forward by setting the next call's `startTime` to the previous
page's **last fill's `time` + 1** -- not by offset/position, which the API
doesn't support -- and stops when a page returns fewer than 2000 fills, or
after 50 pages (a safety valve against an API that never shrinks below the
cap).

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

## Dex coverage (`account_state`)

pathiel's old `LiveVenue.leader_state` only read the main dex plus a
hardcoded `"xyz"`. `account_state` reads main + **every** registered HIP-3
perp dex, resolved once per day via `perpDexs` and cached
(`hl.meta.perp_dexs`, `hl.meta.dex_list`) -- as of 2026-10-02 that's 10
dexes (`xyz, flx, vntl, hyna, km, abcd, cash, para, mkts, io`), not one.
Configurable via `COPYCAT_HL_DEXES` (comma-separated, `""` = main) for
ops/local tuning, or by passing `override=[...]` to `hl.meta.dex_list`
directly.

## Meta caching

Per-dex perp universes (`hl.meta.universe`) cache for 1h
(`COPYCAT_HL_META_TTL_S`); the HIP-3 dex list (`hl.meta.perp_dexs`) caches
for 24h (`COPYCAT_HL_DEX_LIST_TTL_S`); spot prices
(`hl.meta.spot_prices`) cache for 30s (`COPYCAT_HL_SPOT_PRICE_TTL_S`). Every
cache serves its last-known-good value on a fetch failure rather than an
empty result -- a transient API blip must never blank coin resolution or
leader pricing mid-cycle.

## Testing

```
.venv/bin/python -m pytest services/hl/tests          # gate: <2s, no network
.venv/bin/python -m pytest services/hl/tests -m live   # live eval: hits the real API
```

Gate tests (93, ~0.4s) fake `http_post` and the SDK `Exchange` -- no
network, deterministic. They cover: price/size rounding (incl. the
IOC-direction rounding and the integer-size-coin floor), the never-
silently-1 `max_leverage` forced-refresh path, `is_isolated_only`'s
default-False fallback, the timeout guard (including the exact SDK bug --
`timeout=None` passed explicitly, so `setdefault` can't catch it), the
token bucket + documented weight table, `account_state`'s multi-dex
aggregation and HIP-3 coin namespacing, `extras`'s index-based spot
pricing and the illiquid-mark exclusion (including the actual $1B-MAX
shape), `fills` pagination by last-fill-time (not offset) with its
safety-valve page cap, `leaderboard`/`candles` parsing, `set_leverage`'s
strict-error-body check and isolated-only fallback, `market`'s IOC pricing
+ min-size bump + reduce-only passthrough, `close`'s long/short handling,
and the no-key write refusal across all three write methods.

`test_live.py` (6 tests, `@pytest.mark.live`, excluded from the default
gate by `pyproject.toml`'s `addopts = "-m 'not live'"`) hits the real
Hyperliquid mainnet API against `0xe2823659be02e0f48a4660e4da008b5e1abfdf29`
and asserts shape/sanity, not exact numbers (real balances move). Last run
(2026-10-02): `account_state` equity_perp_usd=$454,419.02 across 10 open
positions including a HIP-3 `xyz:TSLA` position; `extras`
spot_other_usd=$13.49, staked_hype_usd=$90,471.03; 128 fills in the last
24h; leaderboard 46,953 rows; `mid(BTC)`=$84,862.50; `max_leverage(BTC)`=40.
