#!/usr/bin/env bash
# Eval: which processes the version-skew guard (GET /api/health `stale`) asks
# you to restart after each kind of change, measured with real git on a
# THROWAWAY worktree of HEAD (removed at the end; your checkout is not touched).
#
#   contracts/evals/build_skew_check.sh
#
# Takes a few seconds. Exit code = failed scenarios.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python contracts/evals/build_skew_check.py
