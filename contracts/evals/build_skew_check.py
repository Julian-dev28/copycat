"""Eval of the version-skew build id (contracts.build) on a THROWAWAY git
worktree of HEAD: real git, real files, real commits, nothing touches the
checkout you run it from.

Outcome it measures: which processes GET /api/health would ask you to restart
after each kind of change. The one that matters is the first: a commit that
touches only the web must not move the engine's id (the engine trades; before
this the id was the commit and every commit flagged it).

usage: build_skew_check.py            (build_skew_check.sh wraps it)
Prints PASS/FAIL per scenario; exit code = failures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
ALL = ["api", "discovery_worker", "engine", "mcp", "scout"]
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def git(wt: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=wt, capture_output=True, text=True, check=True, timeout=30).stdout


SNIPPET = """
import json, sys
from pathlib import Path
from contracts import build
build.ROOT = Path(sys.argv[1])          # this checkout's contracts.build, pointed at the worktree's files
print(json.dumps(build.compute_build_ids()))
"""


def ids(wt: Path, env_build: str = "") -> Dict[str, str]:
    """contracts.build from THIS checkout (so an uncommitted build.py is what runs),
    computed over the files in `wt`."""
    env = {k: v for k, v in os.environ.items() if k != "COPYCAT_BUILD_ID"}
    env["PYTHONPATH"] = str(ROOT)
    if env_build:
        env["COPYCAT_BUILD_ID"] = env_build
    # -P and cwd=ROOT: `contracts` must resolve to this checkout, not the worktree's copy
    r = subprocess.run([PY, "-P", "-c", SNIPPET, str(wt)], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=30)
    if r.returncode != 0:
        sys.exit(f"compute_build_ids failed in {wt}:\n{r.stderr}")
    return json.loads(r.stdout)


def moved(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    return sorted(c for c in before if before[c] != after[c])


def append(wt: Path, rel: str, text: str) -> None:
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(text)


def scenario(name: str, wt: Path, base: Dict[str, str], expect: List[str], edit, commit: bool) -> Dict[str, str]:
    edit()
    if commit:
        git(wt, "add", "-A")
        git(wt, "-c", "user.name=eval", "-c", "user.email=eval@local", "commit", "-q", "-m", f"eval: {name}")
    after = ids(wt)
    got = moved(base, after)
    check(name, got == expect, f"moved {got or 'nothing'}, expected {expect or 'nothing'}")
    return after


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="copycat-build-skew-"))
    wt = tmp / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", "-q", str(wt), "HEAD"], cwd=ROOT, check=True, timeout=60)
    try:
        head = git(wt, "rev-parse", "--short", "HEAD").strip()
        base = ids(wt)
        check("0. ids computed on the worktree at " + head,
              all(len(v) == 12 and v != "unknown" for v in base.values()) and set(base) == set(ALL),
              json.dumps(base))

        # the headline: committed web-only, docs-only and test-only changes move nothing
        base = scenario("1. commit touching only services/web", wt, base, [],
                        lambda: append(wt, "services/web/src/lib/shell/staleBuild.ts", "\n// eval edit\n"), commit=True)
        base = scenario("2. commit touching only docs/ and a package README", wt, base, [],
                        lambda: (append(wt, "docs/ARCHITECTURE.md", "\neval edit\n"),
                                 append(wt, "services/discovery/discovery/scout/README.md", "\neval edit\n")), commit=True)
        base = scenario("3. commit touching only tests and evals", wt, base, [],
                        lambda: (append(wt, "services/engine/tests/eval_touch.py", "x = 1\n"),
                                 append(wt, "services/discovery/evals/eval_touch.py", "x = 1\n")), commit=True)
        # a Scout-only commit restarts scout and the api (it imports discovery), never the engine
        base = scenario("4. commit touching only services/discovery", wt, base, ["api", "discovery_worker", "scout"],
                        lambda: append(wt, "services/discovery/discovery/scout/rows.py", "\n# eval edit\n"), commit=True)
        base = scenario("5. commit touching only services/api", wt, base, ["api"],
                        lambda: append(wt, "services/api/api/routes/health.py", "\n# eval edit\n"), commit=True)
        base = scenario("6. commit touching only services/mcp", wt, base, ["mcp"],
                        lambda: append(wt, "services/mcp/copycat_mcp/server.py", "\n# eval edit\n"), commit=True)
        # engine code: engine, and everyone that imports engine (scout for sizing, the api)
        base = scenario("7. uncommitted edit in services/engine", wt, base, ["api", "discovery_worker", "engine", "scout"],
                        lambda: append(wt, "services/engine/engine/core.py", "\n# eval edit\n"), commit=False)
        base = scenario("8. untracked new module in services/engine", wt, base, ["api", "discovery_worker", "engine", "scout"],
                        lambda: append(wt, "services/engine/engine/eval_new.py", "x = 1\n"), commit=False)
        base = scenario("9. commit touching contracts/models.py", wt, base, ALL,
                        lambda: append(wt, "contracts/models.py", "\n# eval edit\n"), commit=True)
        base = scenario("10. commit touching services/hl (the mcp talks HTTP only)", wt, base,
                        ["api", "discovery_worker", "engine", "scout"],
                        lambda: append(wt, "services/hl/hl/venue.py", "\n# eval edit\n"), commit=True)
        base = scenario("11. deleting a tracked engine file", wt, base, ["api", "discovery_worker", "engine", "scout"],
                        lambda: (wt / "services/engine/engine/eval_new.py").unlink(), commit=False)
        env_ids = ids(wt, env_build="img-eval")
        check("12. COPYCAT_BUILD_ID overrides every component", env_ids == {c: "img-eval" for c in ALL}, json.dumps(env_ids))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, check=False, timeout=60)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT, check=False, timeout=30)
        try:
            tmp.rmdir()
        except OSError:
            pass
    print(f"\n{fails} check(s) failed")
    return fails


if __name__ == "__main__":
    sys.exit(main())
