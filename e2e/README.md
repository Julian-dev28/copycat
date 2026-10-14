# e2e: Playwright against a throwaway copycat

Every run starts its own stack on free ports with a temp data dir and tears it down
after. It never touches `:3000`, `:8787` or `./data` (the harness refuses them), so it
can run on a host where the operator's copycat is trading.

```bash
cd e2e
npm run demo   # web only, demo mode (?demo=1): demo + a11y + visual projects, parallel
npm run full   # the real api, engine and Scout on a temp data dir against the mock Hyperliquid, serial
npm test       # every project, one stack per mode
```

From the repo root: `make e2e-demo`, `make e2e` (demo, then full).

## Lanes

| project  | stack  | what it proves                                                                 |
|----------|--------|--------------------------------------------------------------------------------|
| `demo`   | web    | every page and flow on the deterministic demo fixtures; a demo page never sends a non-GET request |
| `a11y`   | web    | axe on each page, keyboard reach                                               |
| `visual` | web    | the underwhelm sweep tool (`E2E_SWEEP=1`), screenshots per page/state/width/theme |
| `full`   | full   | the product end to end on the mock HL: see below                              |

The `full` project (`tests/full/`, one worker, serial, 2 min per test):

- `scout.spec.ts`: no token means the page asks for one and sends nothing; saving the
  stack token opens Scout. The board ranks the mock leaderboard on its own (the scout
  process's scheduler). A leader "trades" on the mock (`/__mock/trade`), a refresh
  picks it up, and its file shows the round trip and both fills with UTC headers.
  Changing the sim terms in the drawer re-ranks the board from the candle cache: the
  mock's `candleSnapshot` count does not move.
- `trade.spec.ts`: connect an API wallet through the Account page (a throwaway pair from
  `/__mock/keypair`), make it active and the engine picks it up; Settings: trading on is
  one click, dry run off asks "Trade with real money?" (Cancel keeps it on); invest $100
  in a leader from the Trade page; the leader opens 1 BTC on the mock and the engine
  mirrors it with an order signed by our agent key (the mock recovers the signer and
  checks the approval like HL does); the position shows on Portfolio; the leader closes
  and so do we, reduce-only, both books flat.

## The mock Hyperliquid (`mock_hl/server.py`)

Deterministic, offline, stateful. Answers every `/info` type copycat sends in HL's real
shapes, signature-checks `/exchange` actions (the signer must be an agent the account
approved), fills an IOC at mid when its limit crosses, and records every exchange request
decoded (coin, side, size, reduce-only, leverage) so a test can assert what the engine
sent. One spot pair (HYPE/USDC) so `extras` reads succeed. Control plane, never something
copycat calls: `/__mock/reset`, `/__mock/user` (cash, positions, approved agents),
`/__mock/mids`, `/__mock/fail`, `/__mock/trade` (a user trades at mid with no signature;
`time` backdates the fill), `/__mock/keypair`, `/__mock/exchange?since=`, `/__mock/state`
(includes `info_counts` per `/info` type). Gate test: `mock_hl/test_server.py` drives the
REAL `services/hl` venue, SDK signing included, against it over loopback.

The harness (`harness/stack.ts`) gives the python services an environment with every
`COPYCAT_*` variable from the parent shell dropped (no `.env`, no key), an unlimited HL
rate budget, `COPYCAT_E2E=1` (the only way `COPYCAT_HL_BASE_URL` is honored) and
`COPYCAT_DISCOVERY_FRESH_S=0` (no "fetched 15 min ago, still fresh" skip on the fills
tail, so a refresh right after a seeded trade reads it). The engine is started as soon as
the vault file exists, exactly like a first-time user's.

## Debugging

```bash
node harness/cli.ts up full        # keep a stack running; URLs and token in e2e/.stack.json
node harness/aria-dump.ts "/scout?demo=1"   # ARIA tree of a page -> artifacts/aria/
E2E_KEEP=1 npm run full            # keep the temp root (logs/ has api, engine, scout, mock, web logs)
node harness/cli.ts down
```

`E2E_WEB_REF=HEAD` builds the committed web instead of the working tree; `E2E_REBUILD=1`
forces a web rebuild (it is cached per source hash + api URL in `.web-build/`).
