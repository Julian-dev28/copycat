/**
 * Finds user-visible strings in TS/TSX source (string literals, template
 * literal text and JSX text) that use a banned word. Used by the gate test
 * src/lib/copyTerms.test.ts to keep "leader" and "book" out of UI copy
 * (UX_AUDIT.md #6). Heuristic on purpose, tuned to this codebase:
 *
 * - comments are stripped first;
 * - a string counts as copy when it has whitespace or starts with a capital
 *   letter ("Leader", "Your book is full"); a lone lowercase token is a code
 *   identifier (`"leaders"`, `"in_book"`, `"/api/leaders"`) and is skipped;
 * - JSX text is the run between `>` and `<` / `{` that does not look like code.
 */

export interface CopyHit {
  line: number;
  text: string;
  word: string;
}

export const BANNED_COPY = /\b(leaders?|books?|your wallets|my wallets)\b/i;

/** Remove // and /* *\/ comments without touching strings. */
export function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (quote) {
      out += c;
      if (c === "\\") {
        out += n ?? "";
        i += 2;
        continue;
      }
      if (c === quote) quote = null;
      i++;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      out += c;
      i++;
      continue;
    }
    if (c === "/" && n === "/" && (i === 0 || /[\s;,({[]/.test(src[i - 1]))) {
      while (i < src.length && src[i] !== "\n") i++;
      continue;
    }
    // a real block comment never follows a word char: "/api/scout/*" in JSX text is not one
    if (c === "/" && n === "*" && (i === 0 || !/[\w/]/.test(src[i - 1]))) {
      const end = src.indexOf("*/", i + 2);
      const chunk = src.slice(i, end === -1 ? src.length : end + 2);
      out += chunk.replace(/[^\n]/g, " "); // keep line numbers
      i = end === -1 ? src.length : end + 2;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

function lineOf(src: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index; i++) if (src.charCodeAt(i) === 10) line++;
  return line;
}

const looksLikeCopy = (s: string) => /\s/.test(s.trim()) || /^[A-Z]/.test(s.trim());
// `;` only reads as code at a line end or after `)`: prose uses it mid-sentence ("sim; an override").
const looksLikeCode = (s: string) => /=|;\s*$|\);|&&|\|\||\?\s|\w\.\w|\w\(|\)\s*[.:?]/.test(s.replace(/&[a-z]+;/g, "'"));

/** Every user-visible string in `src` that contains a banned word. */
export function scanCopy(src: string, banned: RegExp = BANNED_COPY): CopyHit[] {
  const code = stripComments(src);
  const hits: CopyHit[] = [];
  const push = (text: string, index: number) => {
    const m = text.match(banned);
    if (m && looksLikeCopy(text)) hits.push({ line: lineOf(code, index), text: text.trim(), word: m[1].toLowerCase() });
  };

  // "..." and '...' literals (one line)
  for (const m of code.matchAll(/(["'])((?:\\.|(?!\1)[^\\\n])*)\1/g)) push(m[2], m.index ?? 0);
  // template literals: only the literal chunks, not ${expressions}
  for (const m of code.matchAll(/`((?:\\.|[^\\`])*)`/g)) {
    for (const part of m[1].split(/\$\{[^}]*\}/)) push(part, m.index ?? 0);
  }
  // JSX text
  for (const m of code.matchAll(/[>}]([^<>{}]+)(?=[<{])/g)) {
    if (!looksLikeCode(m[1])) push(m[1], m.index ?? 0);
  }
  // de-duplicate (a JSX string attribute can match twice)
  const seen = new Set<string>();
  return hits.filter((h) => {
    const k = `${h.line}:${h.text}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}
