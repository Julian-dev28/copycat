#!/usr/bin/env bash
# Live eval: stage-B cold vs warm cost (indexing tightening), on a THROWAWAY copycat
# data dir reading real Hyperliquid data. No account, no agent key, trading off
# (Settings() defaults dry_run): nothing this runs can place an order. Two
# `scout refresh` passes over a small universe, no api process, no scheduler --
# just the CLI, twice.
#
#   services/discovery/evals/stats_budget_check.sh [universe]   # default 40
#
# Timing depends on the shared background HL rate-limit bucket's state (see the
# scout README's "Stage-B warm path, live" section): a cold pass on a brand-new
# bucket can take well over 10 minutes for 40 wallets once per-item charges push
# it below the background reserve floor; the warm pass should be much faster
# since it makes far fewer of those charges. Exit code = failed checks.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
MAIN_CHECKOUT="${COPYCAT_MAIN_CHECKOUT:-$HOME/Documents/code/copycat}"   # the venv lives there, not in this worktree
PY="$MAIN_CHECKOUT/.venv/bin/python"
UNIVERSE="${1:-40}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault
echo "throwaway copycat data dir: $T (universe=$UNIVERSE)"
cd "$ROOT"
set +e
env -u COPYCAT_AGENT_KEY -u COPYCAT_ACCOUNT_ADDRESS COPYCAT_SKIP_DOTENV=1 COPYCAT_DATA_DIR="$T" \
  COPYCAT_API_TOKEN="$(openssl rand -hex 32)" COPYCAT_API_PORT=19223 COPYCAT_BIND=127.0.0.1 \
  COPYCAT_HL_PRIORITY=background COPYCAT_NETWORK=mainnet COPYCAT_SCOUT_UNIVERSE="$UNIVERSE" \
  "$PY" "$ROOT/services/discovery/evals/stats_budget_check.py" "$T" "$UNIVERSE"
FAILS=$?
set -e
exit $FAILS
