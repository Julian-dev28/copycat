"""The leader is "they/their" everywhere a user reads about them.

The Scout side said "they" (copyFit, labels: their own tests pin it) while
the Trade side, the engine's skip reasons, the api's MCP plan warnings and
the MCP tool text said "he/his" (2026-10-14 underwhelm sweep: both voices
in one ticket, "copy their biggest bets ... go to his larger positions").
A leader is a real person whose pronouns nobody here knows; one voice.

What is scanned: every string, JSX text and docstring in the web sources,
the e2e tests, the python modules whose strings reach a user (engine
reasons and preview notes, api plan warnings and route descriptions, the
MCP server's tool text and prompts) and the product docs. What is not: code
comments, identifiers (`his` is a series key, `hisCoins`, `his_notional`,
`ourSide(his, dir)`), quoted tokens and markdown code. `segment` and
`protected` below are the exact rule; the one-off migration of 2026-10-15
used them to rewrite the copy, so a new "he" fails here the same way.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[2]

WEB_SRC = ROOT / "services/web/src"
E2E_TESTS = ROOT / "e2e/tests"
PY_USER_FACING = [
    "services/engine/engine/core.py",
    "services/engine/engine/sizing.py",
    "services/engine/engine/public.py",
    "services/api/api/mcp_plans.py",
    "services/api/api/routes/mcp_plans.py",
    "services/api/api/routes/wallets.py",
    "services/api/api/engine_client.py",
    "services/mcp/copycat_mcp/server.py",
    "services/mcp/copycat_mcp/prompts.py",
    "services/mcp/copycat_mcp/api_client.py",
    "services/mcp/evals/demo_check.py",
]
DOCS = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "services/api/README.md",
    "services/discovery/README.md",
    "services/engine/README.md",
    "services/mcp/README.md",
    "services/mcp/DEMO.md",
    "services/discovery/discovery/scout/README.md",
]

PRONOUN = re.compile(r"\b(he|his|him|himself|He|His|Him)\b")
TS_COMMENT_START = ("//", "/*", "*", "*/")
TS_TRAILING = re.compile(r"\s//(\s|$)|\{/\*")
PY_TRAILING = re.compile(r"\s+#\s")
MD_CODE_SPAN = re.compile(r"`[^`]*`")


def lang_of(path: Path) -> str:
    return {".ts": "ts", ".tsx": "ts", ".py": "py", ".md": "md"}[path.suffix]


def segments(text: str, lang: str) -> Iterator[Tuple[int, int, str]]:
    """(line number, offset of the segment in the line, segment): the part of
    each line that a user can read. Comment-only lines and trailing comments
    are dropped; markdown code (fences and spans) is blanked, not removed, so
    offsets stay valid."""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.lstrip()
        if lang == "md":
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            yield i, 0, MD_CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
            continue
        if lang == "ts":
            if s.startswith(TS_COMMENT_START):
                continue
            m = TS_TRAILING.search(line)
            yield i, 0, line[: m.start()] if m else line
            continue
        if s.startswith("#"):
            continue
        m = PY_TRAILING.search(line)
        yield i, 0, line[: m.start()] if m else line


def protected(seg: str, m: "re.Match[str]") -> bool:
    """An identifier or a quoted token, not a word a user reads."""
    before, after = seg[: m.start()], seg[m.end():]
    if m.group(0) not in ("his", "him"):
        return False
    if before.endswith(".") or before.endswith("="):
        return True
    if re.match(r"\s*[:\[\]);}]", after) or re.match(r"\.\w", after) or re.match(r"\s*=[^=>]", after):
        return True
    if re.match(r"\s*(?:[!=]=|[<>]=?)\s", after):                       # a comparison: `his != float(...)`
        return True
    if re.search(r":\s*$", before) and re.match(r"\s*,", after):      # `positions: his,` (destructuring rename)
        return True
    if re.search(r"[(\[,]\s*$", before) and re.match(r"\s*[,)\]]", after):   # a bare argument: `ourSide(his, dir)`
        return True
    q = before[-1:] if before[-1:] in "\"'`" else None
    return bool(q and after.startswith(q))


def hits(text: str, lang: str) -> List[Tuple[int, str, str]]:
    out: List[Tuple[int, str, str]] = []
    for lineno, _, seg in segments(text, lang):
        for m in PRONOUN.finditer(seg):
            if not protected(seg, m):
                out.append((lineno, m.group(0), seg.strip()[:110]))
    return out


def scanned_files() -> List[Path]:
    files = [p for p in WEB_SRC.rglob("*") if p.suffix in (".ts", ".tsx")
             and ".test." not in p.name and p.name != "schema.gen.ts"]
    files += [p for p in E2E_TESTS.rglob("*.ts")]
    files += [ROOT / p for p in PY_USER_FACING]
    files += [ROOT / p for p in DOCS]
    return sorted(set(files))


def test_user_facing_copy_says_they_not_he():
    bad: List[str] = []
    for p in scanned_files():
        assert p.exists(), p
        for lineno, word, ctx in hits(p.read_text(), lang_of(p)):
            bad.append(f"{p.relative_to(ROOT)}:{lineno}: {word!r} in: {ctx}")
    assert not bad, "the leader is they/their in user-facing copy:\n" + "\n".join(bad)


def test_segment_and_protection_rules():
    ts = "\n".join([
        "// he adds",                                                   # comment line: skipped
        "const his = clipFrom(x);   // his index",                      # identifier + trailing comment
        'if (s.key === "his" && s.his.path) return { coin, his };',    # quoted token, member, shorthand
        "if (is_orphan || his != size) return his == last;",             # comparisons
        "export function ourSide(his: Side, dir: D) { return flipSide(his); }",
        "const { equity, positions: his, style } = x;",
        "for (const [list, his] of lists) pool.push({ coin: c, his });",
        '<span title="each of his positions">he trades it</span>',     # two real hits
        "{/* he never */}",
    ])
    assert [(n, w) for n, w, _ in hits(ts, "ts")] == [(8, "his"), (8, "he")]
    py = "\n".join([
        "# he exits",
        "venue.hold(L, 'BTC', 0.0)     # he exits",
        "slice_('DOGE', his=50.0, his_notional_usd=his)",
        'reason="one-shot: only the positions he held when copied"',
    ])
    assert [(n, w) for n, w, _ in hits(py, "py")] == [(4, "he")]
    md = "\n".join(["```", "ourSide(his, dir)", "```", "He trades `his_notional` on his book"])
    assert [(n, w) for n, w, _ in hits(md, "md")] == [(4, "He"), (4, "his")]


def test_scope_is_the_whole_product():
    names = {p.name for p in scanned_files()}
    assert {"TicketDialogs.tsx", "core.py", "mcp_plans.py", "server.py", "ARCHITECTURE.md", "trade.spec.ts"} <= names
    assert "schema.gen.ts" not in names and not any(".test." in n for n in names)


# ── the rewrite the 2026-10-15 migration applied (kept so the rule is testable) ──

IRREGULAR = {"is": "are", "was": "were", "has": "have", "does": "do", "goes": "go",
             "isn't": "aren't", "wasn't": "weren't", "hasn't": "haven't", "doesn't": "don't"}
SIBILANT_ES = {"passes", "pushes", "watches", "fixes", "misses", "crosses", "touches", "reaches", "catches",
               "matches", "finishes", "flushes", "switches", "presses", "guesses", "wishes", "rushes"}
ADVERB = r"(?:already|actually|also|still|never|just|only|then|now|usually|often|rarely|simply|really|first|later)"
HE_VERB = re.compile(r"\b(he|He)\b(?P<adv>(?:\s+" + ADVERB + r")?)\s+(?P<verb>[A-Za-z']+)")


def base_verb(w: str) -> str:
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w in SIBILANT_ES:
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def rewrite(seg: str) -> str:
    """he/his/him -> they/their/them in one segment, with verb agreement
    ("he closes his position" -> "they close their position"); a standalone
    possessive ("Match his", ">his<") -> "theirs"."""
    out: List[str] = []
    pos = 0
    for m in PRONOUN.finditer(seg):
        if protected(seg, m):
            continue
        w = m.group(0)
        start, end, rep = m.start(), m.end(), w
        if w in ("he", "He"):
            v = HE_VERB.match(seg, m.start())
            if v:
                end = v.end()
                rep = ("they" if w == "he" else "They") + v.group("adv") + " " + base_verb(v.group("verb"))
            else:
                rep = "they" if w == "he" else "They"
        elif w == "his":
            standalone = re.match(r"""\s*(?:<|["'`]\s*[\]),}]|\.\s*$)""", seg[end:])
            rep = "theirs" if standalone else "their"       # a line-wrapped "his" at a segment's end is a determiner
        elif w == "His":
            rep = "Their"
        elif w == "him":
            rep = "them"
        elif w == "Him":
            rep = "Them"
        elif w == "himself":
            rep = "themselves"
        out.append(seg[pos:start])
        out.append(rep)
        pos = end
    out.append(seg[pos:])
    return "".join(out)


def rewrite_text(text: str, lang: str) -> str:
    lines = text.split("\n")
    for lineno, _off, seg in segments(text, lang):
        line = lines[lineno - 1]
        if lang == "md":
            # rewrite the prose between code spans, keep the spans byte for byte (a splice by the
            # original offsets shifted once "He trades" became the longer "They trade")
            parts = re.split(r"(`[^`]*`)", line)
            lines[lineno - 1] = "".join(part if i % 2 else rewrite(part) for i, part in enumerate(parts))
        else:
            lines[lineno - 1] = rewrite(seg) + line[len(seg):]
    return "\n".join(lines)


def test_rewrite_keeps_grammar_and_code():
    assert rewrite("Each open copy closes when he closes his position, so you keep his exits.") == \
        "Each open copy closes when they close their position, so you keep their exits."
    assert rewrite("Skip what he already holds; copy only what he opens from now on.") == \
        "Skip what they already hold; copy only what they open from now on."
    assert rewrite("he is short now; he was long; he has it; he does; he goes flat; he did not move") == \
        "they are short now; they were long; they have it; they do; they go flat; they did not move"
    assert rewrite('options={[["match", "Match his"], ["max", "Coin max"]]}') == \
        'options={[["match", "Match theirs"], ["max", "Coin max"]]}'
    assert rewrite('<span className="text-muted">his</span>') == '<span className="text-muted">theirs</span>'
    assert rewrite("countering him (inverted); did your copy track him?") == \
        "countering them (inverted); did your copy track them?"
    assert rewrite("His PnL is in his dollars. When he enters") == "Their PnL is in their dollars. When they enter"
    assert rewrite("`leverage` unset follows his.") == "`leverage` unset follows theirs."
    assert rewrite("a plan replaces this wallet's terms (needs his") == "a plan replaces this wallet's terms (needs their"
    assert rewrite('f"% worse than his "') == 'f"% worse than their "'                 # a string that continues on the next line
    assert rewrite("const his = clipFrom(x); s.his.path; ourSide(his, dir); { coin: c, his }") == \
        "const his = clipFrom(x); s.his.path; ourSide(his, dir); { coin: c, his }"
    assert rewrite_text("# he adds\nx = 1  # he exits\nreason='he held it'", "py") == \
        "# he adds\nx = 1  # he exits\nreason='they held it'"
    assert rewrite_text("He trades `his_notional` on his book", "md") == "They trade `his_notional` on their book"
    assert rewrite_text("- `max_worse_entry_pct` checks OUR side against his entry: `his` stays", "md") == \
        "- `max_worse_entry_pct` checks OUR side against their entry: `his` stays"
