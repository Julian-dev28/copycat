/**
 * Reads the color tokens out of globals.css and resolves them the way the
 * browser would for our blocks (`var()` chains and `color-mix(in srgb ...)`),
 * so tests can check contrast and PnL modes against the real stylesheet.
 * Test-side helper; nothing in the app imports it at runtime.
 */
import { mix } from "./contrast";
import type { PnlMode } from "./pnlMode";

export type Theme = "light" | "dark";
type Decls = Record<string, string>;

export interface Tokens {
  light: Decls;
  dark: Decls;
  /** `:root[data-pnl="..."]` blocks, keyed by mode, declarations without the leading -- */
  modes: Partial<Record<PnlMode, Decls>>;
}

function decls(body: string): Decls {
  const out: Decls = {};
  for (const m of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

export function parseTokens(css: string): Tokens {
  const t: Tokens = { light: {}, dark: {}, modes: {} };
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const sel = (m[1].split(";").pop() ?? "").trim(); // drop a leading `@import ...;`
    if (sel === ":root") Object.assign(t.light, decls(m[2]));
    else if (sel === ".dark") Object.assign(t.dark, decls(m[2]));
    else {
      const mode = sel.match(/^:root\[data-pnl="([\w-]+)"\]$/)?.[1] as PnlMode | undefined;
      if (mode) t.modes[mode] = { ...t.modes[mode], ...decls(m[2]) };
    }
  }
  return t;
}

/** Resolve one token to a hex for a theme and PnL mode. */
export function resolve(t: Tokens, theme: Theme, name: string, mode: PnlMode = "standard", depth = 0): string {
  if (depth > 20) throw new Error(`token cycle at --${name}`);
  const scope: Decls = { ...t.light, ...(theme === "dark" ? t.dark : {}), ...(t.modes[mode] ?? {}) };
  const raw = scope[name];
  if (raw === undefined) throw new Error(`unknown token --${name}`);
  return resolveValue(t, theme, raw, mode, depth + 1);
}

function resolveValue(t: Tokens, theme: Theme, raw: string, mode: PnlMode, depth: number): string {
  const v = raw.trim();
  if (/^#[0-9a-fA-F]{3,8}$/.test(v)) return v.toLowerCase().slice(0, 7);
  const ref = v.match(/^var\(--([\w-]+)\)$/);
  if (ref) return resolve(t, theme, ref[1], mode, depth);
  const cm = v.match(/^color-mix\(in srgb,\s*(.+?)\s+(var\(--[\w-]+\)|[\d.]+%),\s*(.+)\)$/);
  if (cm) {
    const pctRaw = cm[2].startsWith("var(") ? resolveRaw(t, theme, cm[2].slice(6, -1), mode) : cm[2];
    return mix(resolveValue(t, theme, cm[1], mode, depth + 1), parseFloat(pctRaw), resolveValue(t, theme, cm[3], mode, depth + 1));
  }
  throw new Error(`cannot resolve "${v}"`);
}

function resolveRaw(t: Tokens, theme: Theme, name: string, mode: PnlMode): string {
  const scope: Decls = { ...t.light, ...(theme === "dark" ? t.dark : {}), ...(t.modes[mode] ?? {}) };
  return scope[name];
}

export function resolvePnl(t: Tokens, theme: Theme, mode: PnlMode): { up: string; down: string } {
  return { up: resolve(t, theme, "up", mode), down: resolve(t, theme, "down", mode) };
}
