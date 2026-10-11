/**
 * Which character positions changed between two formatted numbers, aligned
 * from the right (so "$9.99" -> "$10.01" marks the digits that moved, and a
 * longer value marks its new leading characters). Pure, unit-tested.
 */
export function changedDigits(prev: string, next: string): Set<number> {
  const out = new Set<number>();
  const offset = next.length - prev.length;
  for (let i = 0; i < next.length; i++) {
    const j = i - offset;
    if (j < 0 || prev[j] !== next[i]) out.add(i);
  }
  return out;
}
