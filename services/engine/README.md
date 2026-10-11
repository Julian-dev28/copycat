# services/engine

The copy engine. Every `poll_interval_s` it reads each leader's positions,
diffs them against what it saw last cycle, and mirrors the change onto your
account with your own sizing and leverage. Real money. No AI.

Public surface (the only names other services import):

| name | what |
|---|---|
| `engine.public.run_forever(venue)` | the worker loop (`python -m engine`) |
| `engine.public.run_cycle(venue, now_ms=None)` | one cycle, returns a summary dict |
| `engine.public.status() -> EngineStatus` | last cycle's snapshot, read from SQLite, no network |
| `engine.public.events(limit, since_ms)` | `EngineEvent`s, newest first |
| `engine.public.preview_wallet(address, req, settings, venue=None)` | Trade ticket preview (`WalletPreview`), read only |
| `engine.public.leader_book(address, venue=None)` | v9: his positions from one account read, `[{coin, side, notional_usd}]` (size x entry); the api hashes it for MCP copy plans |
| `engine.public.read_stops()` | pending `data/stop/<address>.flag` requests |
| `engine.public.leader_events(address, limit, before_ms)` | one wallet's events, newest first (tail read, 8MB cap) |
| `engine.public.wallet_ledgers()` / `archive_wallet(address)` | per-wallet ledger rows; mark a stopped wallet archived (`ArchiveRefused` while it has copies) |
| `engine.sizing.*` | pure sizing/leverage/equity math (discovery's sim imports it), incl. `plan_allocation` |
| `engine.pacing.*` | pure HL read-weight estimate and effective poll interval |

`core.py`, `state.py`, `events.py`, `settings_io.py` are internals.

## Copy rules

Every rule below is pinned by a gate test in `tests/`.

**Ownership**
- One leader per coin. The first leader (in `Settings.leaders` order) to open a
  coin owns our copy of it until our copy closes. Other leaders' moves on that
  coin are skipped ("owned by leader X").
- "Not ours": if your account already holds a coin that has no row in the
  engine's `copies` table (you opened it by hand, or another bot did), the
  engine never touches it and never copies into it.
- Orphans: a leader removed from `Settings.leaders` while we still hold his
  copies keeps having his exits mirrored, but never gets new exposure.

**Exits**
- Exits (reduce, close, flip) mirror even when `enabled` is false. Disabling
  stops new entries only; a copy already on the exchange still follows the
  leader out.
- `dry_run` is a different axis: it blocks ALL writes, exits included. A real
  copy opened while live is frozen during dry_run (skip "real copy held") and
  its leader's last size is held, so the exit fires once you go live again.
- A failed exit is retried every cycle until it succeeds (the leader's
  last-seen size is frozen at the stale value so the diff keeps firing).
  Closes are idempotent: the hl venue sizes them from a fresh read.
- A reduce takes the same fraction off our real size that the leader took off
  his. Reduces are never bumped to the $10.50 minimum: a reduce under it whose
  remainder is above it is skipped and accumulates; a remainder under it
  becomes a full close.
- A flip (long to short in one read) is a close then a fresh open.
- Stranded copy: a copy whose leader is flat and whose last-seen size is also
  flat (the diff would never fire) is closed once that leader reads OK.

**Entries**
- `max_worse_entry_pct`: an open/add is skipped while mid is worse than the
  leader's entry by more than this. The skip is pending, re-checked each cycle.
- `min_order_bump`: a notional under $10.50 but at least 25% of it is rounded
  up to $10.50; smaller is skipped. A bump that would exceed the margin room
  is skipped ("needs more margin than available").
- Margin room cap: notional <= available margin on that dex x leverage x 0.95.
- `max_open_copies`: no new open once this many copies exist (adds still go).
- `only_new_positions`: the first read of a leader is a baseline; what he
  already holds is ignored until he goes flat on it.
- An add to a copy whose leader's previous size is flat: proportional sizes
  off his added notional; fixed modes skip (no fraction to scale).

**Sizing modes** (`engine/sizing.py`)
- `fixed_margin`: notional = `fixed_margin_usd x leverage`.
- `fixed_notional`: notional = `fixed_notional_usd`.
- `proportional`: his added notional / his equity x (our equity x
  `sleeve_frac` / number of leaders) x `size_multiplier`.
- Adds in fixed modes scale OUR real current notional by his fractional add.

- `allocation` (Trade page, "invest $X in this wallet", `allocation_usd`):
  - exposure `match`: his added notional / his equity x allocation (his
    leverage carries through).
  - exposure `target`: his added notional / his gross notional after the
    change x allocation x leverage, where leverage is
    min(`target_leverage`, coin max, `max_position_leverage`), also the
    exchange leverage. Using the capped leverage keeps each slice's margin
    at allocation x his weight, so the wallet's margin is the allocation.
  - Adds use the same formula on his incremental notional, at the copy's own
    leverage. Reduces/closes are unchanged (same fraction he took off).
  - Allocation cap: this wallet's total copy margin (our copies of him at
    mark / leverage, plus orders sent earlier this cycle) stays <=
    allocation x 1.02. An open/add is trimmed to fit; under $10.50 it is
    skipped ("allocation full").
  - Small accounts (`small_account_mode`):
    - `concentrate` (default): at every open/add the eligible set is
      recomputed from his whole book: the smallest slice under $10.50 is
      dropped and the rest renormalized (x his gross / gross left), one at a
      time, until all clear the minimum, so the whole allocation goes into
      his biggest positions. Coins we already copy for him stay eligible
      until he exits. A coin outside the set is skipped and ignored until he
      goes flat on it.
    - `bump`: a slice >= 25% of $10.50 is rounded up if it still fits the
      allocation cap.
    - `skip`: slices under $10.50 are dropped.
    - Other sizing modes: `skip` disables the bump; otherwise
      `min_order_bump` as before.
  - `sizing.plan_copy` is the sibling for global wallets (the Settings tab's
    fixed_margin / fixed_notional / proportional): per position the open
    notional at the exchange leverage, bump, floor, `max_open_copies`, coins
    owned by another wallet, liquidity.
  - `sizing.plan_allocation` runs the same steps in the same order (coin
    name order, like a first-sight batch) and is what the Trade ticket
    preview shows. Not in the preview: our free margin (room cap) and
    prices moving between preview and order.

**Liquidity (large accounts)**: every open/add is capped at
min(`max_order_volume_pct` % of the coin's 24h volume, book depth within
`max_slippage_pct` of mid) (`venue.market_stats`, `venue.depth_usd`). The rest
is carried in kv `catch_up` and sent one capped order per cycle, at the
copy's leverage, through the same room/allocation caps, until filled or he
changes that position (then the diff takes over and the carry is dropped).
A carry under $10.50 is dropped. Paused (kept) while entries are blocked or
the mid is worse than his entry by more than `max_worse_entry_pct`. The
unfilled part of a partially filled IOC joins the carry. The open/add event
says "split: $X now, $Y over the next cycles". If either liquidity read fails,
an order under $50k goes uncapped; a bigger one is skipped and stays pending.
Every order carries `max_slippage_pct`. Exits are not capped: the IOC
slippage band bounds each fill, and partial exits already retry.

**Per-wallet PnL ledger** (SQLite `ledger`): every reduce/close of our copy
(diff, close-all, stop-wallet, a settled ambiguous reduce) books
(fill px - our entry) x size x side - fee into that leader's row. Fill px is
the order's `avg_px`, else the mid. Fees only when the result reports one
(HL order responses do not, so `fees_usd` stays 0 today). Fills before
`invested_ms` are not counted; a new `invested_ms` (fresh investment) resets
the row; a re-post that keeps it does not. Any wallet with `invested_ms`
is synced, including a global copy (override `{invested_ms}` only).

**Wallet status**: every `LeaderStatus` row carries `open_copies`,
`margin_used_usd` (HL `marginUsed`, else notional / leverage),
`exposure_usd`, `unrealized_pnl_usd` (from the raw positions, the same rows
as `EngineStatus.positions`), `realized_pnl_usd`, `fees_usd`, `stopping`. An
orphan's `effective` shows the allocation terms it last ran with.

**Stop one wallet**: `data/stop/<address>.flag` `{close_positions}` (written by
the api, which also removes the wallet from settings). That leader is an
orphan from the cycle the flag is seen, even if settings still list it.
`close_positions` true: every copy of his is closed reduce-only (even in
dry_run, like close-all), `close` events with reason "stop wallet"; a failed
or partial close keeps the flag and retries next cycle (`stopping` true);
once flat the flag is deleted and `skip` "wallet stopped" is logged. False:
the flag is deleted at once; his copies keep following his exits.

**Read-budget pacing** (`engine/pacing.py`): one cycle's /info weight is
estimated as, per account read (ours + each leader), 2 per dex he is active
on + 2 for spot, + 22 per leader with `include_spot_staked`, + 2 per dex we
hold copies on (allMids). The worker sleeps max(`poll_interval_s`,
weight x 60 / (1200 x 0.6)), so the engine uses at most 60% of HL's budget.
25 main-dex leaders: 26 x 4 + 2 = 106 -> 8.83 s. Reported as
`EngineStatus.effective_poll_s` and in the cycle log line (`poll_s`, `read_weight`).

**Leverage modes**: `max` (coin max), `match` (ceil of his), `fixed`
(`leverage`). All capped by the coin max and `max_position_leverage`.
`margin_mode` cross is forced to isolated on isolated-only markets.

**Per-leader overrides**: `leader_overrides[address]` replaces any of sizing
mode, multiplier, fixed amounts, leverage mode/value, margin mode and
`max_worse_entry_pct` for that leader only (`Settings.for_leader`).

**Trade direction (contract v8, `trade_direction`)**: `copy` mirrors his side;
`counter` takes the opposite side of every position he opens (he goes long, we
go short).
- Sizes are identical in both directions: every sizing formula uses |size| x
  price (his notional, his gross notional, our current notional), so only the
  order side flips.
- Opens and adds take OUR side; reduces and closes follow his size changes on
  our position (reduce-only, side read from our real size). A flip is a close,
  then a fresh open on the opposite of his NEW side.
- `max_worse_entry_pct` checks OUR side against HIS entry: a counter short (he
  is long at E) is blocked once mid < E x (1 - p), a counter long (he is
  short) once mid > E x (1 + p). Liquidity caps read the book on our order side.
- Each `copies` / `dry_copies` row stores the `direction` it was opened with,
  and keeps it until it closes. Changing a wallet's direction applies to its
  next fresh open only: an open copy's adds, catch-ups and flips' close keep
  the old side (a flip's new open takes the new direction). Rows from before
  v8 read as `copy`.
- Safety: an add is skipped when our real position is on the other side from
  what the copy's direction says it should be (changed outside copycat);
  adding would net against it. "Not ours" and "vanished" are side-blind
  (any size counts), and the stranded-copy close seeds his last-seen sign
  from ours, inverted for a counter copy.

**Coin filters (v8, `coin_allowlist` / `coin_blocklist`)**: an open/add of a
coin outside a non-empty allowlist, or on the blocklist, is skipped with
"filtered: <coin>" (a fresh open is then ignored until he goes flat, like
"disabled"). Exits are never filtered. Matching is case-insensitive; a HIP-3
coin keeps its "dex:COIN" form ("xyz:TSLA" never matches plain "TSLA"). The
book-wide lists apply to every wallet whose override does not set its own (an
override's list, even [], replaces the book-wide one). Sizing still sees his
whole book: a filtered coin's slice is left unspent, never handed to the
other coins (`sizing.coin_allowed`).

**Pause (v8, `paused`)**: a paused wallet (its override, or the book-wide
flag) gets no new opens or adds (skip "paused"; a fresh open is ignored until
he goes flat; a liquidity catch-up waits); exits always mirror. Pausing is
not stopping: the wallet stays in the book and its copies keep following him
out.

**One-shot (v9, `one_shot`, set by an MCP copy plan with follow=false)**: the
first cycle that sees it for this `invested_ms` records his held coins and sides
(kv `one_shot`, event `baseline` "one-shot: ..."). Only a first open of one of
those, same side, is allowed, including a pending `max_worse_entry_pct` retry and
a liquidity catch-up. An add ("one-shot: adds not copied"), a flip's new side, a
reopen after he closed, or a new coin ("one-shot: only the positions he held
when copied") is skipped and ignored until he goes flat. Exits always mirror.
Turning it off drops the record. The engine never writes settings.

**Skip events carry their leader** (v8): a coin's skip reason is logged (once,
when it first appears or changes) with the leader being diffed, so
`leader_events` shows one wallet why its moves were not copied.

**Archived wallets** (v8, ledger `archived_ms`, set through the api for a
stopped wallet with no copies): an archived orphan is no longer read every
cycle. One that still holds any copy row (real or dry-run) or has a pending
stop is read as before, so its exits always mirror. A new `invested_ms` (a
fresh investment) clears `archived_ms`.

**Day PnL (UTC)** = equity now - equity at the day anchor (first cycle of the
UTC day) - net transfers since the anchor. Transfers come from our own HL
`userNonFundingLedgerUpdates` (`Venue.ledger_updates`, read every cycle, weight
20, counted in `engine.pacing`), classified by `engine/daypnl.py`: deposits,
withdrawals (+ fee), USDC `send` / `spotTransfer` / `internalTransfer` /
`subAccountTransfer` in or out (+ fee), vault deposit/withdraw. Spot<->perp
`accountClassTransfer` nets to 0 (both sides are in equity); liquidations are
PnL. A mid-day deposit or withdrawal does not move day PnL.

The number is **unreliable** (`EngineStatus.day_pnl_reliable = false`) when the
ledger read fails, a row has an unknown type or bad amount, or a transfer sits
within 15 s of the account read (it may or may not be in that equity). Then
`day_pnl_usd` is the day's last reliable value (or None) and one `error` event
("day PnL unreliable: ...") is logged per stretch.

**Daily loss halt**: `daily_loss_limit_usd < 0` blocks new opens/adds once day
PnL is at or below it. Exits keep mirroring. Emits `halt` / `resume` on
transitions. An unreliable cycle never starts or ends a halt: the previous
state and reason hold (the reason gets "day PnL unreliable now; holding")
until a reliable cycle, a new UTC day, or the limit set to 0.

**Equity**: standard accounts use perp `accountValue` + spot USDC. Unified
account / portfolio margin (`AccountState["abstraction"]`) use spot USDC +
open-position uPnL, since spot already holds the perp collateral. Measured
2026-10-03 on a live unified wallet: HL portfolio $533,932, this formula
$526,638 (1.4%), perp+spot $966,342 (81% over). `tests/test_live_equity.py`
(eval lane) re-checks it. If the account read has no `abstraction` key the
standard formula is used.

## Order safety (contract v2)

- Every order carries a client order id (cloid). For a fresh open the
  `copies` row is written as pending BEFORE the order is sent, so a crash or
  timeout can never leave an untracked real position.
- Ambiguous open: the row stays pending. Next cycle: if we hold the coin it is
  promoted (a partly filled IOC reports "canceled", so the position decides,
  not the status); else `order_status(cloid)` decides; "unknown" is only
  believed 30s after sending. Not filled: row deleted, coin ignored while the
  leader holds it.
- Ambiguous reduce: never re-sent blind. Parked in kv `pending_reduces`; once
  HL settles it, what filled is re-derived from our real size and the
  remainder is retried.
- Partial fills: a partial open is a real, confirmed copy; the event logs the
  filled notional. A partial reduce freezes the leader's size at a value that
  makes next cycle take off exactly the unfilled part. A partial close keeps
  the copy and retries. Every add/reduce reads our REAL size from the account.
- Isolation: an exception in one coin or one leader is logged as an `error`
  event and the cycle continues; exits of every other leader still run.

## Our copy vanished (liquidation)

Each live cycle checks every confirmed copy against our account read. A copy
missing from one read is marked pending; missing on the second consecutive
read it is dropped, its coin ignored while the leader holds it, and one `skip`
event is logged: "our copy vanished (liquidated or closed outside copycat),
last liq px X". Status never shows zero-size rows.

## Emergency close-all

`POST /api/engine/close-all` sets `enabled=false` and writes
`data/close_all.flag`. The next cycle closes every `copies` row reduce-only
(even in dry_run; "not ours" positions untouched), clears `dry_copies`, runs
the normal cycle with entries forced off, and deletes the flag once nothing
remains (logs `halt` "close-all complete"). A failed close keeps the flag.

## State

`$COPYCAT_DATA_DIR` (resolved to an absolute path at startup):
- Which account: re-resolved every cycle (`engine/account.py`): the vault's active
  account once the vault is authoritative, else `COPYCAT_ACCOUNT_ADDRESS`. No account:
  the cycle idles (no reads, no orders, status `our_address` null). A change is logged
  (`intent`, or `error` when the old account still has copies, which are then no longer
  managed until it is active again).
- `engine-<address>.db`: state is per account, so copies opened under account A are never
  managed while B is active. A pre-v6 `engine.db` is renamed to its owner's file (the
  address in its last status snapshot, or `COPYCAT_ACCOUNT_ADDRESS` if it has none).
- `engine_status.json`: the last cycle's `EngineStatus` (what `status()` returns);
  `status(address)` reads that account's own db. `engine_account.json`: the account
  the last cycle ran for.
- `engine-<address>.db` (SQLite, WAL): `leaders` (last positions + ignored coins per
  leader), `copies` (real copies, `pending_cloid`), `dry_copies` (dry-run
  shadow with simulated size; cleared when `dry_run` flips), `kv`
  (`last_good_settings`, `last_status`, `day_anchor` {day, equity_usd, ts_ms}, `day_pnl_good`,
  `day_pnl_problem`, `halted`, `halted_reason`, `last_skips`,
  `last_marks`, `vanish_pending`, `pending_reduces`, `last_dry_run`, `catch_up`), `ledger`
  (per-leader realized PnL since `invested_ms`, plus the wallet's last terms).
- `events.jsonl`: append-only `EngineEvent` log, written as events happen (so
  a crash mid-cycle keeps them). Rotates once at 25MB.
- `engine.lock`: flock held by the running worker.
- `stop/<address>.flag`: stop-one-wallet requests (api writes, engine deletes).
- `settings.json` is read every cycle; invalid or missing keeps the last good.

## Worker loop

One thread runs cycles back to back; the next starts only after the previous
returns, then sleeps `max(0, poll_interval_s - elapsed)`. A slow cycle (the
~20s first full dex scan) never stacks: the next one just starts late.
`poll_interval_s` is re-read from settings every cycle. A second worker on
the same data dir exits 1 (`EngineAlreadyRunning`). An exception backs off
exponentially to 60s. SIGTERM finishes the current cycle and exits without
sleeping. `status()` is how the api reads the engine: the last snapshot from
SQLite, with `running` true if the last cycle is within max(30s, 3x poll).

## Risks

- No stop losses anywhere. At max isolated leverage a copy liquidates after
  an adverse move of about `1/leverage - maintenance` (40x: about 1.25%). The
  engine only learns of it afterwards ("our copy vanished").
- Cross margin shares collateral: one bad copy can liquidate others.
- Copies enter after the leader, at a worse price, and exit after him.
- Day PnL nets transfers by ledger type. A new HL ledger type makes day PnL
  unreliable (the halt holds) until `engine/daypnl.py` learns it. A transfer
  between 00:00 UTC and a pre-upgrade anchor (no `ts_ms`) is counted twice
  on the upgrade day only.

## Running and tests

    COPYCAT_SKIP_DOTENV=1 env -u COPYCAT_AGENT_KEY COPYCAT_DATA_DIR=/tmp/x .venv/bin/python -m engine   # scratch
    .venv/bin/python -m pytest services/engine          # gate, <1s
    .venv/bin/python -m pytest services/engine -m live  # eval, hits HL (read-only)

## Fixed-size cap (fixed_margin / fixed_notional)

In the fixed sizing modes one copy is one fixed-size position: at most
`max(fixed_margin_usd x exchange leverage, $10.50) x 1.02` (fixed_margin) or
`max(fixed_notional_usd, $10.50) x 1.02` (fixed_notional), measured at our
entry price. The leader's adds can top a copy up to that size (an open that was
trimmed, split or partially filled) but never past it; once full, his adds are
skipped with "add capped". Before this cap, dozens of tiny adds each bumped to
$10.50 grew a $1-margin copy to $126 of margin, and one liquidation took a $100
account to -127% (found by the discovery sim, 2026-10-05; regression tests
`test_fixed_margin_copy_never_grows_past_its_fixed_size` and
`test_fixed_notional_add_tops_up_a_partial_open_but_not_past_it`). Use the
allocation or proportional modes to follow his scaling.
