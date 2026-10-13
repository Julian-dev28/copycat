#!/usr/bin/env bash
# Proves services/mcp/DEMO.md works, step by step, on a THROWAWAY copycat:
# temp data dir (a copy of data/discovery.db for Scout data), trading off, no
# account, no agent key, its own port. Nothing it does can trade or touch
# your live copycat.
#
#   services/mcp/evals/demo_check.sh                 # free: real MCP over stdio, no Claude
#   services/mcp/evals/demo_check.sh --with-claude   # + the doc's prompts through real Claude Code
#   services/mcp/evals/demo_check.sh --with-claude 0x<trader>
#
# Prints PASS/FAIL per step and the transcript paths. Exit code = failures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WITH_CLAUDE=0
if [[ "${1:-}" == "--with-claude" ]]; then WITH_CLAUDE=1; shift; fi
TRADER="${1:-auto}"     # auto: the best Copy Fit trader with 5+ trades and open positions
PORT="${COPYCAT_DEMO_PORT:-18962}"
T="$(mktemp -d)"
cp "$ROOT"/data/discovery.db* "$T"/ 2>/dev/null || true
"$ROOT/.venv/bin/python" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
TOK="$(openssl rand -hex 32)"
( cd "$ROOT" && COPYCAT_DATA_DIR="$T" COPYCAT_API_TOKEN="$TOK" COPYCAT_API_PORT="$PORT" COPYCAT_BIND=127.0.0.1 \
  COPYCAT_SKIP_DOTENV=1 COPYCAT_MCP_ALLOW_TRADING=1 \
  PYTHONPATH=.:services/hl:services/engine:services/discovery:services/api:services/vault \
  env -u COPYCAT_AGENT_KEY nohup .venv/bin/python -m api > "$T/api.log" 2>&1 & )
trap 'kill $(lsof -t -iTCP:'"$PORT"' -sTCP:LISTEN) 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/api/health" && break; sleep 1; done
MTOK="$(cat "$T/mcp_token")"
echo "throwaway copycat on :$PORT, data $T"
echo
set +e
( cd "$ROOT" && PYTHONPATH=.:services/mcp .venv/bin/python services/mcp/evals/demo_check.py \
    "http://127.0.0.1:$PORT" "$TOK" "$MTOK" "$TRADER" "$T/transcript_tools.md" )
FAILS=$?
set -e
[[ -f "$T/trader.txt" ]] && TRADER="$(cat "$T/trader.txt")"
if [[ $WITH_CLAUDE == 1 ]]; then
  echo
  echo "== the doc's prompts through real Claude Code =="
  "$ROOT/.venv/bin/python" -c "import json; json.dump({'enabled': False, 'dry_run': True}, open('$T/settings.json','w'))"
  cat > "$T/mcp.json" <<JSON
{"mcpServers": {"copycat": {"command": "$ROOT/services/mcp/run.sh", "args": [],
  "env": {"COPYCAT_API_URL": "http://127.0.0.1:$PORT", "COPYCAT_MCP_TOKEN": "$MTOK",
          "COPYCAT_SKIP_DOTENV": "1", "COPYCAT_MCP_ALLOW_TRADING": "1"}}}}
JSON
  cd "$T"
  M=(--mcp-config "$T/mcp.json" --strict-mcp-config --allowedTools "mcp__copycat__*" --output-format stream-json --verbose --max-turns 30)
  claude -p "Use copycat: show me the top 5 traders on the Scout board by Copy Fit, one line each." "${M[@]}" < /dev/null > c1.jsonl
  claude -p -c "Explain trader $TRADER's strategy in plain words: style, how long he holds, win rate, biggest risks. Use his fingerprint." "${M[@]}" < /dev/null > c2.jsonl
  claude -p -c "Make a copy plan for $TRADER with \$50 at 3x, 50% entry deviation, copy his side, follow new positions. Show me the plan." "${M[@]}" < /dev/null > c3.jsonl
  CODE="$(curl -s -H "Authorization: Bearer $TOK" "localhost:$PORT/api/mcp/plans/pending" \
    | "$ROOT/.venv/bin/python" -c 'import json,sys; p=json.load(sys.stdin); print(p[0]["confirm_code"] if p else "")')"
  claude -p -c "Yes, I approve. The code copycat shows me is $CODE." "${M[@]}" < /dev/null > c4.jsonl
  "$ROOT/.venv/bin/python" - "$T" "$CODE" "$TRADER" <<'PY'
import json, os, sys
T, CODE, TRADER = sys.argv[1], sys.argv[2], sys.argv[3].lower()
def turn(f):
    tools, final = [], ""
    for line in open(os.path.join(T, f)):
        try: e = json.loads(line)
        except ValueError: continue
        if e.get("type") == "assistant":
            tools += [c["name"].split("__")[-1] for c in e["message"].get("content", []) if c.get("type") == "tool_use"]
        if e.get("type") == "result":
            final = e.get("result") or ""
    return [t for t in tools if t != "ToolSearch"], final
out, fails = [], 0
expect = {"c1.jsonl": "scout_list", "c2.jsonl": "trader_fingerprint", "c3.jsonl": "copy_plan", "c4.jsonl": "execute_copy_plan"}
for f, want in expect.items():
    tools, final = turn(f)
    ok = want in tools and (f == "c4.jsonl" or "execute_copy_plan" not in tools)
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  claude turn {f[1]}: called {tools}")
    out.append(f"## turn {f[1]}\ntools: {tools}\n\n{final}\n")
leak = any(CODE and CODE.upper() in open(os.path.join(T, f)).read().upper() for f in ("c1.jsonl", "c2.jsonl", "c3.jsonl"))
print(f"{'PASS' if not leak else 'FAIL'}  the code never appeared before you typed it")
fails += leak
st = json.load(open(os.path.join(T, "settings.json")))
ok = TRADER in [a.lower() for a in st.get("leaders", [])]
print(f"{'PASS' if ok else 'FAIL'}  the trader landed in the book"); fails += not ok
open(os.path.join(T, "transcript_claude.md"), "w").write("\n".join(out))
print(f"Claude transcript: {T}/transcript_claude.md")
sys.exit(fails)
PY
  FAILS=$((FAILS + $?))
fi
echo
[[ $FAILS == 0 ]] && echo "DEMO CHECK: ALL PASS" || echo "DEMO CHECK: $FAILS FAILED"
exit $FAILS
