#!/usr/bin/env bash
# Behavioral eval (periodic lane, costs Claude usage): does `write_thesis`
# produce a thesis that clears the quality bar in
# docs/research/user_consensus_2026-10.md ("Thesis quality rubric": 12
# criteria, 0-2 each, pass = total >= 18/24 with no criterion at 0)?
#
# Starts a THROWAWAY api (temp data dir, a copy of data/discovery.db for
# Scout data, trading off, no account, no agent key), registers the MCP
# READ-ONLY (no COPYCAT_MCP_ALLOW_TRADING anywhere: execute_copy_plan does
# not exist for this eval). For each of three real trader addresses (one
# intraday crypto wallet, one HIP-3 stock-perp wallet, one small-sample
# wallet, chosen to exercise different fingerprint shapes):
#   1. a real `claude -p` session runs the /copycat-thesis flow over the
#      MCP tools and saves the thesis with save_thesis;
#   2. the saved thesis is read back from the api (admin token, this
#      script's own read, never the model's) and checked deterministically
#      against prompts.missing_sections() -- the same check save_thesis
#      itself reports;
#   3. a second, independent `claude -p` call (no tools, just text) scores
#      the thesis against the rubric and answers with JSON.
# Exit code = number of theses that did not pass. Results are also appended
# to services/mcp/README.md by hand after a run (see that file's "Thesis
# eval" section).
#
# Usage: services/mcp/evals/thesis_eval.sh [addr1 addr2 addr3]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"   # override: a worktree checkout has no .venv of its own (shared venv)
EVAL_PY="$ROOT/services/mcp/evals/thesis_eval.py"
PORT="${COPYCAT_THESIS_EVAL_PORT:-18963}"
# Real wallets, chosen for different fingerprint shapes (reconciled by hand
# against raw Hyperliquid data on 2026-10-14, see the QA report):
#   1. intraday crypto, hit HL's 10k-fill cap (truncation caveat exercised)
#   2. HIP-3 stock-perp, a large still-open scaled position outside its
#      counted trips (hidden-pnl caveat exercised)
#   3. small sample (demo's signature wallet): exercises the sample-size hedge
ADDRS=("${1:-0x0871deb34bfd2052b1c10dc4f6c0912a2a47e927}"
       "${2:-0x2eaca7c0b93064c8f5c9c67cd2415cf68724bcef}"
       "${3:-0xedab6e3998ffddcb354094ffe8ca2a3cff8d3370}")

T="$(mktemp -d)"
cp "$ROOT"/data/discovery.db* "$T"/ 2>/dev/null || true
"$PY" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
TOK="$(openssl rand -hex 32)"
( cd "$ROOT" && COPYCAT_DATA_DIR="$T" COPYCAT_API_TOKEN="$TOK" COPYCAT_API_PORT="$PORT" COPYCAT_BIND=127.0.0.1 \
  COPYCAT_SKIP_DOTENV=1 \
  PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault \
  env -u COPYCAT_AGENT_KEY nohup "$PY" -m api > "$T/api.log" 2>&1 & )
trap 'kill $(lsof -t -iTCP:'"$PORT"' -sTCP:LISTEN) 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/api/health" && break; sleep 1; done
# Read-only: the MCP gets the api's own scoped token, no ALLOW_TRADING
# anywhere, so execute_copy_plan is not even registered.
MTOK="$(cat "$T/mcp_token")"
cat > "$T/mcp.json" <<JSON
{"mcpServers": {"copycat": {"command": "$ROOT/services/mcp/run.sh", "args": [],
  "env": {"COPYCAT_API_URL": "http://127.0.0.1:$PORT", "COPYCAT_MCP_TOKEN": "$MTOK",
          "COPYCAT_SKIP_DOTENV": "1", "COPYCAT_PYTHON": "$PY"}}}}
JSON
echo "throwaway copycat on :$PORT, data $T"
# --allowedTools is a pre-approval allowlist, NOT a sandbox: other tools stay
# callable and would otherwise just prompt. Without COPYCAT_PYTHON above, a
# worktree checkout (no .venv of its own) makes run.sh fail to launch, the
# MCP connection never comes up, and a capable model reaches for Bash to
# hand-roll its own stdio MCP client instead of failing loudly (seen on a
# 2026-10-14 run before this fix: 28 Bash calls, zero mcp__copycat__* calls,
# a real thesis saved anyway through a hand-written client). --disallowedTools
# below makes the restriction real, so a future regression here fails
# visibly (no thesis saved) instead of silently working around itself.
M=(--mcp-config "$T/mcp.json" --strict-mcp-config --allowedTools "mcp__copycat__*" \
   --disallowedTools "Bash" "Read" "Write" "Edit" "NotebookEdit" "Glob" "Grep" "WebFetch" "WebSearch" "Task" \
   --output-format stream-json --verbose --max-turns 40)

FAILS=0
for ADDR in "${ADDRS[@]}"; do
  echo
  echo "== $ADDR: write_thesis =="
  claude -p "Use the copycat MCP server's write_thesis prompt for the trader $ADDR and follow it exactly: \
gather evidence with the tools in the order it says, write the thesis with every required ## section in \
order (including a standalone Invalidation section, separate from Confidence & caveats), cite trades by \
coin, side and UTC date, hedge every claim when the sample is small, no financial advice framing, then \
save it with save_thesis and tell me the title and the edge line. If save_thesis reports missing \
sections, fix the draft and save again before you finish." \
    "${M[@]}" < /dev/null > "$T/write_$ADDR.jsonl" 2>"$T/write_$ADDR.err" || true

  curl -s -H "Authorization: Bearer $TOK" "localhost:$PORT/api/scout/traders/$ADDR/thesis" \
    > "$T/theses_$ADDR.json"
  "$PY" - "$T/theses_$ADDR.json" "$T/thesis_$ADDR.md" <<'PY'
import json, sys
theses = json.load(open(sys.argv[1]))
cc = [t for t in theses if t.get("source") == "claude_code"]
md = max(cc, key=lambda t: t.get("created_ms") or 0)["markdown"] if cc else ""
open(sys.argv[2], "w").write(md)
print(f"saved claude_code thesis: {len(md)} chars" if md else "NO claude_code thesis was saved")
PY

  if [[ ! -s "$T/thesis_$ADDR.md" ]]; then
    echo "=== $ADDR: FAIL (no thesis was saved; see $T/write_$ADDR.jsonl) ==="
    FAILS=$((FAILS + 1))
    continue
  fi

  PYTHONPATH="$ROOT/services/mcp" "$PY" -c "
from copycat_mcp.prompts import THESIS_SECTIONS, missing_sections
md = open('$T/thesis_$ADDR.md').read()
missing = missing_sections(md)
print('missing_sections:', missing or 'none')
open('$T/sections_$ADDR.txt', 'w').write('\n'.join(THESIS_SECTIONS))
" | tee "$T/missing_$ADDR.txt"
  if ! grep -q "^missing_sections: none$" "$T/missing_$ADDR.txt"; then
    echo "=== $ADDR: FAIL (missing_sections, see above) ==="
    FAILS=$((FAILS + 1))
    continue
  fi

  curl -s -H "Authorization: Bearer $TOK" "localhost:$PORT/api/scout/traders/$ADDR/fingerprint" \
    > "$T/fp_$ADDR.json" || true

  echo "== $ADDR: judge =="
  "$PY" "$EVAL_PY" judge-prompt "$T/thesis_$ADDR.md" "$T/sections_$ADDR.txt" "$T/fp_$ADDR.json" \
    > "$T/judge_prompt_$ADDR.txt"
  claude -p "$(cat "$T/judge_prompt_$ADDR.txt")" --output-format json < /dev/null > "$T/judge_raw_$ADDR.json" \
    2>"$T/judge_$ADDR.err" || true
  "$PY" -c "
import json
raw = json.load(open('$T/judge_raw_$ADDR.json'))
open('$T/judge_result_$ADDR.txt', 'w').write(raw.get('result') or '')
" || cp "$T/judge_raw_$ADDR.json" "$T/judge_result_$ADDR.txt"

  if ! "$PY" "$EVAL_PY" score "$ADDR" "$T/judge_result_$ADDR.txt"; then
    FAILS=$((FAILS + 1))
  fi
done

echo
echo "transcripts and theses kept at $T"
echo "$FAILS of ${#ADDRS[@]} theses failed the rubric"
exit "$FAILS"
