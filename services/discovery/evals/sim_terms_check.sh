#!/usr/bin/env bash
# Live eval: ScoutSimTerms (contract v16) on a THROWAWAY copycat stack reading real
# Hyperliquid data. Temp data dir, trading off, no account, no agent key, its own
# ports. Nothing it does can trade or touch your live copycat.
#
#   services/discovery/evals/sim_terms_check.sh
#
# Takes 2 to 6 minutes solo (longer if another throwaway stack is sharing the HL
# background-priority budget at the same time: stage B is the bottleneck, not this
# eval's own checks). Exit code = failed checks.
#
# Beside a live copycat (shared per-IP HL budget, COPYCAT_HL_BUCKET_PATH set) a COLD
# first build cannot finish in time: 20 wallets measured 32 min of stage B and a stage C
# starved of candles (30 s waits) on 2026-10-15. Seed the throwaway from the live
# scout's database instead; what this eval proves (on-the-fly re-sim from cache, the
# default terms against the live-style ones, validation) is a warm-board property:
#
#   COPYCAT_SIM_TERMS_SEED_DB=~/Documents/code/copycat/data/discovery.db \
#   COPYCAT_HL_BUCKET_PATH=~/Documents/code/copycat/data/hl_rate.bucket \
#     services/discovery/evals/sim_terms_check.sh
#
# The seed is a read-only sqlite backup (the live file is never written); the operator's
# own stored terms and any queued refresh request are dropped from the copy, so the
# throwaway starts on the documented default. stats_budget_check.sh covers the cold path.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# A worktree has no .venv of its own (it lives in the main checkout only); fall back to
# that when this script runs from a worktree (qa2/*) rather than the main checkout.
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="/Users/julian_dev/Documents/code/copycat/.venv/bin/python"
PORT="${COPYCAT_SIM_TERMS_EVAL_PORT:-18976}"
T="$(mktemp -d)"
TOK="$(openssl rand -hex 32)"
"$PY" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
if [ -n "${COPYCAT_SIM_TERMS_SEED_DB:-}" ]; then
  "$PY" - "${COPYCAT_SIM_TERMS_SEED_DB/#\~/$HOME}" "$T/discovery.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
src.close()
# the copy keeps the fills, funding and candle caches, the stats and sims and the
# last board; the operator's terms and a queued request must not leak into the throwaway
dst.execute("DELETE FROM scout_meta WHERE k IN ('sim_terms', 'refresh_requested')")
dst.commit()
n = dst.execute("SELECT COUNT(*) FROM scout_stats").fetchone()[0]
dst.close()
print(f"seeded {sys.argv[2]} from {sys.argv[1]}: {n} wallets with stats (the first build is a warm pass)")
EOF
fi
# Absolute paths (not relative "."): sim_terms_check.py itself imports contracts/
# discovery.scout, and must resolve them whatever directory this script is run from.
export PYTHONPATH="$ROOT:$ROOT/services/hl:$ROOT/services/engine:$ROOT/services/discovery:$ROOT/services/api:$ROOT/services/vault"
ENV=(env -u COPYCAT_AGENT_KEY -u COPYCAT_ACCOUNT_ADDRESS COPYCAT_SKIP_DOTENV=1 COPYCAT_DATA_DIR="$T"
     COPYCAT_API_TOKEN="$TOK" COPYCAT_API_PORT="$PORT" COPYCAT_BIND=127.0.0.1 COPYCAT_HL_PRIORITY=background
     COPYCAT_SCOUT_UNIVERSE="${COPYCAT_SCOUT_UNIVERSE:-40}" COPYCAT_NETWORK=mainnet)
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is busy (a previous run still up?): set COPYCAT_SIM_TERMS_EVAL_PORT or kill it" >&2; exit 2
fi
( cd "$ROOT" && exec "${ENV[@]}" "$PY" -m api > "$T/api.log" 2>&1 ) & echo $! > "$T/api.pid"
( cd "$ROOT" && exec "${ENV[@]}" "$PY" -m discovery.scout serve > "$T/scout.log" 2>&1 ) & echo $! > "$T/scout.pid"
trap 'kill $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true; sleep 1; kill -9 $(cat "$T/api.pid") $(cat "$T/scout.pid") 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/api/health" && break; sleep 1; done
echo "throwaway copycat on :$PORT, data $T (api.log, scout.log kept there)"
echo
set +e
"$PY" "$ROOT/services/discovery/evals/sim_terms_check.py" "http://127.0.0.1:$PORT" "$TOK"
FAILS=$?
set -e
echo "scout log tail:"; tail -6 "$T/scout.log" | cut -c1-160
exit $FAILS
