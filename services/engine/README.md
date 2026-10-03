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
| `engine.sizing.*` | pure sizing/leverage/equity math (discovery's sim imports it) |

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

**Leverage modes**: `max` (coin max), `match` (ceil of his), `fixed`
(`leverage`). All capped by the coin max and `max_position_leverage`.
`margin_mode` cross is forced to isolated on isolated-only markets.

**Per-leader overrides**: `leader_overrides[address]` replaces any of sizing
mode, multiplier, fixed amounts, leverage mode/value, margin mode and
`max_worse_entry_pct` for that leader only (`Settings.for_leader`).

**Daily loss halt**: `daily_loss_limit_usd < 0` blocks new opens/adds once
today's PnL (equity now minus equity at the first cycle of the UTC day) is at
or below it. Exits keep mirroring. Not deposit-adjusted: a mid-day deposit
reads as profit, a withdrawal as loss. Emits `halt` / `resume` on transitions.

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
- `engine.db` (SQLite, WAL): `leaders` (last positions + ignored coins per
  leader), `copies` (real copies, `pending_cloid`), `dry_copies` (dry-run
  shadow with simulated size; cleared when `dry_run` flips), `kv`
  (`last_good_settings`, `last_status`, `day_anchor`, `halted`, `last_skips`,
  `last_marks`, `vanish_pending`, `pending_reduces`, `last_dry_run`).
- `events.jsonl`: append-only `EngineEvent` log, written as events happen (so
  a crash mid-cycle keeps them). Rotates once at 25MB.
- `engine.lock`: flock held by the running worker.
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
- Daily loss halt is not deposit-adjusted.

## Running and tests

    COPYCAT_SKIP_DOTENV=1 env -u COPYCAT_AGENT_KEY COPYCAT_DATA_DIR=/tmp/x .venv/bin/python -m engine   # scratch
    .venv/bin/python -m pytest services/engine          # gate, <1s
    .venv/bin/python -m pytest services/engine -m live  # eval, hits HL (read-only)
