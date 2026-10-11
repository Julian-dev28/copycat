/**
 * Keyboard model for radio groups and tablists (WAI-ARIA APG): arrows move
 * and wrap, Home/End jump, disabled items are skipped. Returns the next index,
 * or null when the key is not ours. Pure, unit-tested.
 */
export function nextRovingIndex(key: string, current: number, count: number, disabled: (i: number) => boolean = () => false): number | null {
  if (count <= 0) return null;
  const step = (from: number, dir: 1 | -1) => {
    for (let k = 1; k <= count; k++) {
      const i = (from + dir * k + count * k) % count;
      if (!disabled(i)) return i;
    }
    return null;
  };
  const first = () => step(-1, 1);
  const last = () => step(count, -1);
  switch (key) {
    case "ArrowRight":
    case "ArrowDown":
      return step(current, 1);
    case "ArrowLeft":
    case "ArrowUp":
      return step(current, -1);
    case "Home":
      return first();
    case "End":
      return last();
    default:
      return null;
  }
}
