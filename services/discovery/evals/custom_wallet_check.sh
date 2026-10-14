#!/usr/bin/env bash
# Live eval: a custom wallet added to the Scout board is built and ranked WHILE a
# full refresh runs, on a THROWAWAY copycat stack reading real Hyperliquid data.
# Temp data dir, trading off, no account, no agent key, its own ports. Nothing it
# does can trade or touch your live copycat.
#
#   services/discovery/evals/custom_wallet_check.sh                # default wallet
#   services/discovery/evals/custom_wallet_check.sh 0x<wallet>     # any wallet
#
# Takes 2 to 6 minutes (a 40-wallet universe refresh runs in the background while
# the custom wallet is served). Exit code = failed checks.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WALLET="${1:-0xedab6e3998ffddcb354094ffe8ca2a3cff8d3370}"
PORT="${COPYCAT_CUSTOM_EVAL_PORT:-18975}"
T="$(mktemp -d)"
TOK="$(openssl rand -hex 32)"
"$ROOT/.venv/bin/python" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
export PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault
ENV=(env -u COPYCAT_AGENT_KEY -u COPYCAT_ACCOUNT_ADDRESS COPYCAT_SKIP_DOTENV=1 COPYCAT_DATA_DIR="$T"
     COPYCAT_API_TOKEN="$TOK" COPYCAT_API_PORT="$PORT" COPYCAT_BIND=127.0.0.1 COPYCAT_HL_PRIORITY=background
     COPYCAT_SCOUT_UNIVERSE="${COPYCAT_SCOUT_UNIVERSE:-40}" COPYCAT_NETWORK=mainnet)
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is busy (a previous run still up?): set COPYCAT_CUSTOM_EVAL_PORT or kill it" >&2; exit 2
fi
# `exec` so the subshell pid IS the python pid; `( a && b & )` would hand us the
# subshell's pid and the trap would leave the api and scout running after the run.
( cd "$ROOT" && exec "${ENV[@]}" .venv/bin/python -m api > "$T/api.log" 2>&1 ) & echo $! > "$T/api.pid"
( cd "$ROOT" && exec "${ENV[@]}" .venv/bin/python -m discovery.scout serve > "$T/scout.log" 2>&1 ) & echo $! > "$T/scout.pid"
trap 'kill $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true; sleep 1; kill -9 $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/api/health" && break; sleep 1; done
echo "throwaway copycat on :$PORT, data $T (api.log, scout.log kept there)"
echo
set +e
"$ROOT/.venv/bin/python" "$ROOT/services/discovery/evals/custom_wallet_check.py" "http://127.0.0.1:$PORT" "$TOK" "$WALLET"
FAILS=$?
set -e
echo "scout log tail:"; tail -4 "$T/scout.log" | cut -c1-160
exit $FAILS
