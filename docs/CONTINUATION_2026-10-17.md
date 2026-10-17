# Continuation, 2026-10-17

Handoff for the next Claude Code session, opened in this folder. The previous sessions ran from
`~/Documents/code/pathiel` and their memory lives there, so everything that matters is here.

## State at shutdown

- `main` at `850f448`, pushed, working tree clean. Contract version 18. CI: Python gate, web lint,
  typecheck, vitest, build, openapi freshness (`.github/workflows/ci.yml`). Playwright lanes are not in CI.
- The local operation was shut down on 2026-10-17 ~10:30: engine, api, scout, the web dev server on
  :3000, a leftover web dev server on :3100 and a leftover e2e mock HL. `data/` and `.env` untouched.
  Every copycat temp dir under `/var/folders/.../T/` (59 eval and e2e throwaways, 33 GB, mostly
  `discovery.db` copies) was removed.
- Live account: `COPYCAT_ACCOUNT_ADDRESS=0x2c2e4efF574B3Fd9879AdeF9c5CAC6fD7C916985`, equity about
  $15, mainnet, trading was enabled and dry run off; the book was empty (4 wallets stopped). Settings
  sizing is **proportional, 19% sleeve**: at $15 every proportional copy is cents and skipped
  (`docs/qa/unclear_2026-10-16.md` #7 and the 2f0a9aa ticket note). Custom "Set leverage" copies do work.
- `.env` holds `COPYCAT_API_TOKEN`, `COPYCAT_ACCOUNT_ADDRESS`, `COPYCAT_AGENT_KEY` (an API wallet key:
  never the master key). `data/api_token` and `data/mcp_token` exist (0600). `COPYCAT_MCP_ALLOW_TRADING`
  is not set anywhere. The copycat MCP is **not registered** in Claude Code (`make mcp-install RUN=1`).

## Bring it back up

```bash
cd ~/Documents/code/copycat
make dev            # api :8787 + engine + scout + web :3000, logs in the terminal; Ctrl-C stops all
```

Or by hand, each logging to a file (the previous sessions did this; the engine recipe is the one that
matters, it must not see `.env`'s key through dotenv):

```bash
export PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault:services/mcp
mkdir -p /tmp/copycat-live
nohup .venv/bin/python -m api >> /tmp/copycat-live/api.log 2>&1 &
nohup .venv/bin/python -m discovery.scout serve >> /tmp/copycat-live/scout.log 2>&1 &
PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault \
  env -u COPYCAT_AGENT_KEY COPYCAT_ACCOUNT_ADDRESS=0x2c2e4efF574B3Fd9879AdeF9c5CAC6fD7C916985 \
  COPYCAT_API_TOKEN="$(grep -E '^COPYCAT_API_TOKEN=' .env | cut -d= -f2-)" COPYCAT_BIND=127.0.0.1 \
  COPYCAT_API_PORT=8787 COPYCAT_DATA_DIR=$PWD/data COPYCAT_NETWORK=mainnet \
  COPYCAT_WEB_ORIGIN=http://localhost:3000 COPYCAT_SKIP_DOTENV=1 \
  nohup .venv/bin/python -m engine >> /tmp/copycat-live/engine.log 2>&1 &
cd services/web && nohup npm run dev >> /tmp/copycat-live/web.log 2>&1 &
```

Health: `TOK=$(grep -E '^COPYCAT_API_TOKEN=' .env | cut -d= -f2-); curl -s -H "Authorization: Bearer $TOK" http://127.0.0.1:8787/api/health`
lists every build with `stale`; a stale engine means its code changed under it, restart it (it trades:
only with Julien's "restart engine"). api and scout restart freely (no orders).

Finding the pids: the command line is `.../Python.app/Contents/MacOS/Python -m engine` (capital P), so
`pgrep -f "python -m engine"` finds nothing. Use
`ps -axo pid,command | grep -E "[P]ython -m engine$|[P]ython -m api$|[d]iscovery\.scout serve"`.
Start services with literal commands, never `python $CMD` (zsh does not split the variable: the api was
down two minutes that way).

## Rules the sessions worked under (CLAUDE.md of the pathiel repo, kept here on purpose)

- Tests and evals with every change; commit and push after each task; say what to restart.
- Never commit secrets (`.env`, `api_token`, `mcp_token`, `*.db`, `data/vault`, `machine.key`,
  `accounts.json`, `audit.jsonl`, `mcp_plans.json`, `passphrase_guard.json`;
  `tests/invariants/test_tracked_files.py` guards the names). No `--no-verify`, no destructive ops
  without confirmation. Gate merges with `set -e` and explicit checks, never `| tail` to judge
  (a `pytest | tail` once hid a failing test and a migration ran on it).
- Agents and tests never use `:3000`, `:8787` or `./data`: demo mode (`?demo=1`) or a temp
  `COPYCAT_DATA_DIR` with `env -u COPYCAT_AGENT_KEY COPYCAT_SKIP_DOTENV=1`. Read the live sqlite
  read-only (`file:...?mode=ro` or `.backup`). Look only (no clicks) in the live app.
- Anything that reads real Hyperliquid beside the live stack sets
  `COPYCAT_HL_BUCKET_PATH=$PWD/data/hl_rate.bucket COPYCAT_HL_PRIORITY=background` (the HL budget
  is per IP), one such eval at a time, each as its own background job (2 h cap).
- The MCP never gets a tool that flips enabled/dry_run, changes leverage or sizing, halts, closes a
  position or touches `/api/accounts` (`services/api/api/auth.py` `MCP_SCOPE`;
  `services/api/tests/test_mcp_security.py`).
- The leader is "they/their" in every user-facing string (`tests/invariants/test_copy_voice.py`).

## Gate and evals

```bash
.venv/bin/python -m pytest -p no:cacheprovider        # 1557 tests; do not add -q (drops the summary)
cd services/web && npm run lint && npm run typecheck && npm test   # 762 vitest
make e2e-demo        # Playwright demo lane (demo + a11y + visual), throwaway web stack, 57 tests
make e2e             # demo, then the full lane: mock HL + api + engine + scout, 5 tests (e2e/README.md)
make openapi         # after a route change: openapi.json + web types (CI fails if stale)
```

Live evals (real HL, one at a time, with the bucket env above):
`services/discovery/evals/stats_budget_check.sh 20` (stage B cold vs warm, ~1 h, slows the live scout
and fails 8 to 13 of its reads: no idle window exists on this host), `sim_terms_check.sh`
(`COPYCAT_SIM_TERMS_SEED_DB` with a `.backup` of the live db), `history_check.sh`,
`services/mcp/evals/demo_check.sh` (real MCP over stdio against a throwaway api, 21 checks, ~2 min,
removes its multi-GB temp copy on exit). Records live in `services/discovery/discovery/scout/README.md`.

## What shipped 2026-10-14 to 2026-10-17 (newest first)

- 850f448 MCP demo eval expects the v15/v16 research tools; cleans its temp dir.
- a058ecd what-if starts from the board's sim terms, "Invest $ at Nx" sizing, liquidated coins named.
- a266036 the unclear sweep: `30d | 24h | Fit` list header, segmented controls never truncate,
  what-if explains proportional sizing. `docs/qa/unclear_2026-10-16.md`.
- 2f0a9aa native `<dialog>` close echo wiped the ticket's confirm chain ("Copy at this leverage
  anyway" did nothing); skipped rows say why; size dead end offers "Invest $15 at Nx".
- 51e4060, 974e14a stage B summary per path and over built wallets; budget eval judges the warm path.
- 1f027d8 README account buttons. 811bcb2 they/their everywhere. b30b938 ETA capped at the stage cap.
- 9c60e86 full e2e lane (connect, go live, copy, engine mirrors on the mock), HL bucket wait meter,
  illiquid-mark log roll-up. Mock HL gained `/__mock/trade`, `/__mock/keypair`, a HYPE/USDC pair.
- 2026-10-15 earlier: Copyable preset (v18), billing by what HL metered, heartbeats on time, cache-only
  re-sim guard, discovery runs API retired, eval records.
- 2026-10-14: the qa2 swarm merges (indexing warm path, trade history v17, sim terms v16, underwhelm
  sweep), custom wallets v15, HL bucket sharing (`COPYCAT_HL_BUCKET_PATH`), version-skew build ids.

## Open follow-ups

1. **Small-account defaults.** Julien's rule: copying must work at any account size. Global
   proportional sizing cannot at $15; the ticket now steers to "Invest $ at Nx". Consider making
   allocation sizing the Settings default for accounts under ~$100, or a first-run prompt.
2. **Eval contention.** Every real-HL eval beside the live scout costs it 8 to 13 failed reads per hour
   (`hl.http` gives up after a 30 s bucket wait). Options: a longer background `max_wait`
   (fewer failures, slower pass) or evals from another IP. Not decided.
3. **e2e lanes in CI.** Playwright install and minutes: Julien's call.
4. **Wide tables** clip at the panel edge with only a fade cue (`TableScroll`); macOS hides scrollbars.
   A stronger cue is a design call. **Phone Trade sheet** is `glass`; looked transparent only in
   headless captures, check on a device.
5. **Board staleness.** `stale` on ~117/200 live rows: the hourly stats pass clears 37 to 108 wallets
   under the shared budget (budget 28,800 weight, 50 min cap). A budget or cadence question, not copy.
6. **README screenshots** TODO (no binaries in the repo rule).
7. **1 liquidation at 1x** report from Julien: not reproduced on 0x36ac…7568 (0 liq in every 1x run);
   the what-if line now names the liquidated coin, trace it when it shows again.

## Lessons worth keeping

- The native `<dialog>` fires `close` after a programmatic close too; `Dialog`/`Drawer` ignore that echo.
- `SegmentedControl` items are grid tracks; a parent that lets it shrink still truncates: add `shrink-0`.
- A pronoun migration rewrites the tests that pin pronouns; protect identifiers (`his != x`,
  `f(his, dir)`), never splice markdown code spans by original offsets.
- `scout refresh` output is the only record of a pass's failures: evals print failed wallets and
  bucket give-ups per read type now.
- Restart recipes: literal commands, capital-P `ps` patterns, health curl after every restart.
