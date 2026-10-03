#!/usr/bin/env bash
# Launcher for the copycat MCP server, safe to call from any cwd:
#   claude mcp add copycat -s user -- /abs/path/to/copycat/services/mcp/run.sh
# Uses the repo's .venv and puts the repo root + services/mcp on PYTHONPATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="${COPYCAT_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  echo "copycat-mcp: $PY not found. Run 'make install' in $ROOT first." >&2
  exit 1
fi
unset COPYCAT_AGENT_KEY
export PYTHONPATH="$ROOT:$HERE${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m copycat_mcp "$@"
