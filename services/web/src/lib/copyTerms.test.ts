import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { scanCopy, stripComments } from "./copyScan";

/**
 * Gate: no user-visible "leader", "book" or "Your wallets" anywhere in the
 * web app (UX_AUDIT.md #6, glossary in src/lib/labels.ts). Code identifiers
 * (`settings.leaders`, `"in_book"`, `/api/leaders`) are not copy and pass.
 */

const SRC = path.resolve(import.meta.dirname, "..");

/**
 * Strings that contain a banned word but are not shown to a user.
 * file (relative to src) -> exact trimmed texts. Keep this short and justified.
 */
const ALLOW: Record<string, string[]> = {};

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.ts$|\.gen\.ts$/.test(name)) out.push(p);
  }
  return out;
}

const SKIP_FILES = new Set([
  "lib/copyScan.ts", // defines the banned pattern
  "lib/labels.ts", // the glossary names the banned words on purpose
]);

describe("UI copy uses the glossary (no leader / book)", () => {
  const files = walk(SRC).filter((f) => !SKIP_FILES.has(path.relative(SRC, f)));

  it("scans a real number of files", () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it("has no banned words in user-visible strings", () => {
    const offenders: string[] = [];
    for (const f of files) {
      const rel = path.relative(SRC, f);
      const allowed = new Set(ALLOW[rel] ?? []);
      for (const h of scanCopy(readFileSync(f, "utf8"))) {
        if (!allowed.has(h.text)) offenders.push(`${rel}:${h.line} [${h.word}] ${h.text}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("scanCopy (the scanner itself)", () => {
  it("catches copy in literals, templates and JSX text", () => {
    const src = [
      `const a = "Add to book";`,
      `const b = \`Your book is full (\${n} leaders)\`;`,
      `const c = <p>Check your leaders</p>;`,
      `const d = { label: "Leader" };`,
      `const e = <h2>Your wallets</h2>;`,
    ].join("\n");
    expect(scanCopy(src).map((h) => [h.line, h.word])).toEqual([
      [1, "book"],
      [4, "leader"],
      [2, "book"],
      [3, "leaders"],
      [5, "your wallets"],
    ]);
  });

  it("ignores identifiers, api paths and comments", () => {
    const src = [
      `const x = settings.leaders.length;`,
      `apiFetch("/api/leaders");`,
      `const k = "in_book";`,
      `type T = Omit<S, "leaders" | "leader_overrides">;`,
      `// the book is the set of leaders`,
      `/* Your book is full */`,
      `{/* leaders list */}`,
      `const y = a > leaders.length ? 1 : 0; const z = <div>{x}</div>;`,
    ].join("\n");
    expect(scanCopy(src)).toEqual([]);
  });

  it("keeps line numbers when stripping block comments", () => {
    const src = `/* one\ntwo */\nconst a = "the book";`;
    expect(stripComments(src).split("\n").length).toBe(3);
    expect(scanCopy(src)[0].line).toBe(3);
  });

  it("reads JSX text with a glob path or an HTML entity as copy", () => {
    expect(scanCopy(`<p>get <span>/api/scout/*</span>. Add to book here.</p>`)).toHaveLength(1);
    expect(scanCopy(`<p>{x} Your leaders&apos; own positions</p>`)).toHaveLength(1);
  });

  it("does not treat // inside a string as a comment", () => {
    expect(scanCopy(`const u = "https://x.y/z leaders";`)).toHaveLength(1);
  });
});
