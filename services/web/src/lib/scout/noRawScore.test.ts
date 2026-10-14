import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * TraderScore.score (contracts/models.py) is an internal sort key: a
 * risk-adjusted ratio with a too-few-trades band hacked onto the bottom
 * (services/discovery/discovery/scoring.py), so a raw value like "-200.00"
 * means nothing to a user and must never render. Where a user needs the
 * "why", Copy Fit (0..100) and flags already explain it (lib/scout/copyFit.ts).
 *
 * Pattern of ui/tableScroll.test.ts: walk every .ts/.tsx under src/ and fail
 * on the raw-score patterns the contract's v16 comment names: `score.score`
 * (reading the field off a TraderScore-shaped object), `.score.toFixed`
 * (formatting it directly) and `formatScore` (the deleted scoreExplain.ts
 * helper -- if it comes back under any name, the scanner should still be
 * updated here, not bypassed).
 */
const SRC = path.resolve(import.meta.dirname, "..", "..");
const SELF = path.resolve(import.meta.dirname, "noRawScore.test.ts");
const PATTERNS = ["score.score", ".score.toFixed", "formatScore"];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (name === "node_modules" || name.endsWith(".test.ts") || name.endsWith(".test.tsx")) continue;
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".ts") || p.endsWith(".tsx")) out.push(p);
  }
  return out;
}

function rawScoreHits(): string[] {
  const hits: string[] = [];
  for (const file of walk(SRC)) {
    if (file === SELF) continue;
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      for (const pat of PATTERNS) {
        if (line.includes(pat)) hits.push(`${path.relative(SRC, file)}:${i + 1}: ${line.trim()}`);
      }
    });
  }
  return hits;
}

describe("the raw score never renders", () => {
  it("no score.score, .score.toFixed or formatScore anywhere in src/", () => {
    expect(rawScoreHits()).toEqual([]);
  });

  it("the scanner itself would catch a reintroduction", () => {
    const tmp = ["const x = row.score.score;", "t.score.toFixed(2)", "formatScore(t)"];
    for (const line of tmp) expect(PATTERNS.some((p) => line.includes(p))).toBe(true);
  });
});
