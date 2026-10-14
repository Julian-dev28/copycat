"""Nothing generated or secret is tracked by git.

e2e/.web-build is the e2e lane's throwaway copy of services/web (e2e/harness/
stack.ts buildWeb). It was committed in the first wip checkpoints before
e2e/.gitignore listed it, so every e2e run dirtied 300+ tracked files and a
`git add -A` carried a stale second copy of the web sources into history.
`.gitignore` only stops new files; an already-tracked path stays tracked, so
this checks the index itself, the same way the secrets list is checked.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Paths that must never be in the index: build copies and the live operator's
# secrets (CLAUDE.md "never commit secrets"; data/ holds the vault and keys).
NEVER_TRACKED = [
    "e2e/.web-build",
    "e2e/.stack.json",
    ".env",
    "data",
    "services/web/.next",
]


def _tracked(prefix: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", prefix], cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, out.stderr
    return [line for line in out.stdout.splitlines() if line]


def test_generated_and_secret_paths_are_not_tracked():
    # data/.gitkeep is the one intended file: it keeps the empty dir in a fresh clone.
    tracked = {p: [f for f in _tracked(p) if Path(f).name != ".gitkeep"] for p in NEVER_TRACKED}
    offenders = {p: files[:5] for p, files in tracked.items() if files}
    assert offenders == {}, f"tracked but must not be: {offenders}"


def test_secret_file_names_are_not_tracked_anywhere():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    names = {"api_token", "mcp_token", "machine.key", "accounts.json", "audit.jsonl", "mcp_plans.json", "passphrase_guard.json"}
    hits = [f for f in out.stdout.splitlines() if Path(f).name in names or f.endswith(".db")]
    assert hits == [], hits
