#!/usr/bin/env bash
# Live eval: trade history correctness (contract v17, user_consensus Trade
# history correctness checklist) against a THROWAWAY copycat stack reading
# real Hyperliquid data. Temp data dir, trading off, no account, no agent
# key, its own ports. Nothing it does can trade or touch your live copycat.
#
#   services/discovery/evals/history_check.sh                 # default 3 wallets
#   services/discovery/evals/history_check.sh 0xA 0xB 0xC      # any 3 wallets
#
# Default wallets (public on-chain addresses, chosen for
# services/discovery/tests/fixtures/history/make_fixtures.py, see its
# docstring): a real HL liquidation, a real single-fill flip, and a
# funding-heavy multi-day hold.
#
# Takes 1 to 4 minutes (on-demand builds for 3 wallets plus a small universe
# refresh in the background). Exit code = failed checks.
#
# STATUS 2026-10-14: a real run against this wallet set found a genuine bug
# (fixed in this branch: scout/rows.py fill_view used HL's raw per-fill
# `liquidation` bool, which also fires on a counterparty absorbing someone
# else's liquidation -- 16 false "Liquidated" fills for a wallet with 1 real
# one) and otherwise confirmed the funding-per-trip and no-trip-spans-a-flip
# checks clean (48 trips replayed, 0 mismatched; 31 funded trips, 0
# mismatched). The run was stopped mid-way by the operator: every throwaway
# stack shares Hyperliquid's per-IP rate limit with the live trading engine
# on this host, and a parallel qa2 throwaway stack was adding enough load to
# risk the live engine's own reads. A clean full run is PENDING -- the
# operator runs this serially, alone, after the qa2 branches merge.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# The venv lives only in the main checkout (common qa2 brief); a worktree has none.
# `cd "$ROOT"` below still runs THIS tree's code (the worktree), only the python
# binary itself comes from the main checkout.
PY="${COPYCAT_VENV_PYTHON:-$HOME/Documents/code/copycat/.venv/bin/python}"
W1="${1:-0x5d908c88be270889c0953e7dff1c8e1d699ceea3}"   # real liquidation
W2="${2:-0x057e4ef25b051110f91102d71ae9fecb2e913220}"   # real single-fill flip
W3="${3:-0x0682f4ee106d167ca46ed015918e83f6f4e5b571}"   # funding-heavy hold
PORT="${COPYCAT_HISTORY_EVAL_PORT:-19231}"
T="$(mktemp -d)"
TOK="$(openssl rand -hex 32)"
"$PY" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
export PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault
ENV=(env -u COPYCAT_AGENT_KEY -u COPYCAT_ACCOUNT_ADDRESS COPYCAT_SKIP_DOTENV=1 COPYCAT_DATA_DIR="$T"
     COPYCAT_API_TOKEN="$TOK" COPYCAT_API_PORT="$PORT" COPYCAT_BIND=127.0.0.1 COPYCAT_HL_PRIORITY=background
     COPYCAT_SCOUT_UNIVERSE="${COPYCAT_SCOUT_UNIVERSE:-20}" COPYCAT_NETWORK=mainnet)
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is busy (a previous run still up?): set COPYCAT_HISTORY_EVAL_PORT or kill it" >&2; exit 2
fi
( cd "$ROOT" && exec "${ENV[@]}" "$PY" -m api > "$T/api.log" 2>&1 ) & echo $! > "$T/api.pid"
( cd "$ROOT" && exec "${ENV[@]}" "$PY" -m discovery.scout serve > "$T/scout.log" 2>&1 ) & echo $! > "$T/scout.pid"
trap 'kill $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true; sleep 1; kill -9 $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/api/health" && break; sleep 1; done
echo "throwaway copycat on :$PORT, data $T (api.log, scout.log kept there)"
echo
set +e
"$PY" "$ROOT/services/discovery/evals/history_check.py" "http://127.0.0.1:$PORT" "$TOK" "$W1" "$W2" "$W3"
FAILS=$?
set -e
echo "scout log tail:"; tail -4 "$T/scout.log" | cut -c1-160
exit $FAILS
