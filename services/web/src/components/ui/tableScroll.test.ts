import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Keyboard users scroll a wide table with the arrow keys only when the
 * scroll container is in the tab order. A bare `overflow-x-auto` div is not
 * (axe: scrollable-region-focusable), so every horizontal scroller in
 * components/ must be a `TableScroll` (Table.tsx: role region + tabIndex 0
 * when labelled), a tablist (its roving arrow keys move focus, and focus
 * scrolls the strip), or an element that carries `tabIndex={0}` itself.
 * The QA swarm found Scout's file tables, Discover's results and the
 * Portfolio positions table all unreachable this way.
 */
const COMPONENTS = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".tsx")) out.push(p);
  }
  return out;
}

function rawScrollers(): string[] {
  const hits: string[] = [];
  for (const file of walk(COMPONENTS)) {
    if (file.endsWith(path.join("ui", "Table.tsx"))) continue;
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      if (!line.includes("overflow-x-auto")) return;
      if (line.includes('role="tablist"') || line.includes("tabIndex={0}")) return;
      hits.push(`${path.relative(COMPONENTS, file)}:${i + 1}: ${line.trim()}`);
    });
  }
  return hits;
}

describe("horizontal scrollers are keyboard reachable", () => {
  it("no bare overflow-x-auto outside TableScroll, tablists and tabIndex={0} elements", () => {
    expect(rawScrollers()).toEqual([]);
  });

  it("the scanner itself sees through to the TableScroll definition", () => {
    const table = readFileSync(path.join(COMPONENTS, "ui", "Table.tsx"), "utf8");
    expect(table).toMatch(/tabIndex=\{label \? 0 : undefined\}/);
    expect(table).toMatch(/role=\{label \? "region" : undefined\}/);
  });
});
