"""Deterministic half of thesis_eval.sh: the rubric, the judge prompt, and
JSON parsing / pass-fail math. No network, no Claude call lives here --
thesis_eval.sh shells out to `claude -p` for the write and judge passes and
hands this script their output to score.

Rubric is copied from docs/research/user_consensus_2026-10.md (the
"Thesis quality rubric" section, written after interviewing copycat's
target users): 12 criteria, 0-2 each, max 24. Pass bar: total >= PASS_TOTAL
AND no criterion scores 0 (a single 0, e.g. an invented number or advice
framing, disqualifies regardless of total). Keep this list word-for-word
in sync with that doc; test_thesis_eval_rubric in services/mcp/tests pins
the count and the two constants below.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

MAX_PER_CRITERION = 2
PASS_TOTAL = 18       # out of 24
MAX_TOTAL = 24


class Criterion(NamedTuple):
    num: int
    name: str
    bar_for_2: str   # what earns the top score; put in the judge prompt so it scores the bar, not vibes


RUBRIC: Tuple[Criterion, ...] = (
    Criterion(1, "Edge stated as one falsifiable sentence",
              "One sentence, specific, states the claimed source of returns in a way a reader could "
              "check against the evidence"),
    Criterion(2, "Entry behavior backed by cited evidence, not assertion",
              "Fingerprint percentages AND specific trades cited by coin, side, and UTC date"),
    Criterion(3, "Sizing and risk quantified",
              "Avg and max leverage, worst trip as % of equity, and concentration all stated"),
    Criterion(4, "Exit behavior quantified",
              "Loser-hold-vs-winner-hold ratio and payoff ratio both stated with numbers"),
    Criterion(5, "Timing/activity disclosed",
              "UTC hours/weekdays and opens-per-day or activity level stated"),
    Criterion(6, "Copier-specific risk addressed",
              "Names at least two of: min-order-size fit at a stated account size, liquidation distance "
              "at the copier's own leverage, latency sensitivity for short holds/breakout entries"),
    Criterion(7, '"What to learn" is concrete and practicable',
              "Multiple concrete, checkable habits a reader could paper-trade"),
    Criterion(8, "Confidence hedged to sample size",
              "Sample size (trips, window) stated up front and every pattern claim hedged when the "
              "count is small (copycat's own prompt puts this at ~30 round trips)"),
    Criterion(9, "States what would change the view (kill criteria)",
              "A specific, separate statement (its own section, not folded into caveats) of what "
              "evidence would invalidate the thesis or change the reader's mind"),
    Criterion(10, "No financial-advice framing",
              'Purely descriptive throughout, no "you should"'),
    Criterion(11, "Numbers traceable to tool output",
              "Every number in the thesis can be matched to a tool call result (fingerprint, profile, "
              "trades, candles)"),
    Criterion(12, "Format discipline",
              "All required `##` sections present in order, under 20,000 characters, no em dashes"),
)
assert len(RUBRIC) == 12
assert MAX_TOTAL == len(RUBRIC) * MAX_PER_CRITERION


def judge_prompt(thesis_markdown: str, required_sections: List[str], fingerprint_json: str = "") -> str:
    """The second `claude -p` call's prompt: apply the rubric to one thesis
    and answer with JSON only. fingerprint_json (optional) lets the judge
    check criterion 11 (traceability) against the actual tool data the
    writer had, not just internal consistency."""
    rows = "\n".join(f"{c.num}. {c.name} -- top score (2) needs: {c.bar_for_2}" for c in RUBRIC)
    sections = ", ".join(required_sections)
    fp_block = (f"\n\nThe fingerprint data the writer had access to (for checking criterion 11, "
                f"traceability):\n```json\n{fingerprint_json}\n```" if fingerprint_json else "")
    return f"""You are scoring a Hyperliquid trader strategy thesis against a fixed rubric. Score strictly:
most real theses should NOT get a perfect score. A criterion scores 0 when it fails outright (missing,
invented, or advice framing), 1 when it is present but weak or partial, 2 only when it clearly clears
the bar described.

Rubric (12 criteria, 0-2 each, max 24):
{rows}

Required section headings, in order: {sections}

Thesis to score:
---
{thesis_markdown}
---
{fp_block}

Answer with ONLY a JSON object, no markdown fencing, no prose before or after:
{{"scores": {{"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 0, "9": 0, "10": 0, "11": 0,
"12": 0}}, "notes": {{"1": "one short reason per criterion, same keys"}}}}
"""


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """The judge's answer, tolerant of ```json fences or stray prose around the object."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def score_result(judge_json: Dict[str, Any]) -> Tuple[int, Dict[int, int], List[str]]:
    """(total, per-criterion scores, problems). A missing or out-of-range
    criterion counts as 0 and is listed as a problem, never silently dropped."""
    scores = judge_json.get("scores") or {}
    per: Dict[int, int] = {}
    problems: List[str] = []
    for c in RUBRIC:
        raw = scores.get(str(c.num), scores.get(c.num))
        try:
            v = int(raw)
        except (TypeError, ValueError):
            v = 0
            problems.append(f"criterion {c.num} ({c.name}): no score returned, counted 0")
        if not 0 <= v <= MAX_PER_CRITERION:
            problems.append(f"criterion {c.num} ({c.name}): out-of-range score {raw!r}, clamped")
            v = max(0, min(MAX_PER_CRITERION, v))
        per[c.num] = v
    return sum(per.values()), per, problems


def passes(total: int, per: Dict[int, int]) -> bool:
    return total >= PASS_TOTAL and all(v > 0 for v in per.values())


def format_report(address: str, total: int, per: Dict[int, int], notes: Dict[str, Any]) -> str:
    lines = [f"=== {address}: {total}/{MAX_TOTAL} {'PASS' if passes(total, per) else 'FAIL'} ==="]
    for c in RUBRIC:
        v = per.get(c.num, 0)
        flag = " <-- 0 disqualifies" if v == 0 else ""
        note = notes.get(str(c.num), "")
        lines.append(f"  {c.num:>2}. [{v}/2] {c.name}{flag}" + (f" -- {note}" if note else ""))
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: thesis_eval.py judge-prompt <thesis.md> [required_sections.txt] [fingerprint.json]"
              "\n       thesis_eval.py score <address> <judge_output.txt>", file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "judge-prompt":
        md = Path(argv[2]).read_text()
        sections = Path(argv[3]).read_text().splitlines() if len(argv) > 3 and argv[3] else []
        fp = Path(argv[4]).read_text() if len(argv) > 4 and argv[4] and Path(argv[4]).exists() else ""
        print(judge_prompt(md, sections, fp))
        return 0
    if cmd == "score":
        address = argv[2]
        raw = Path(argv[3]).read_text()
        parsed = extract_json(raw)
        if parsed is None:
            print(f"=== {address}: FAIL (judge output was not parseable JSON) ===")
            print(raw[:2000])
            return 1
        total, per, problems = score_result(parsed)
        print(format_report(address, total, per, parsed.get("notes") or {}))
        for p in problems:
            print(f"  ! {p}")
        return 0 if passes(total, per) else 1
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
