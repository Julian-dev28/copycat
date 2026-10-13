/** Page scroll as a percent, for the hairline under the header (components/shell/ScrollProgress.tsx). */
export function scrollProgressPct(scrollY: number, scrollHeight: number, viewportHeight: number): number {
  const max = scrollHeight - viewportHeight;
  if (!Number.isFinite(max) || max <= 0) return 0;
  return Math.min(100, Math.max(0, (scrollY / max) * 100));
}
