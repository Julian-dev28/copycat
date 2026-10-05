/**
 * Scout's two views. /discover (custom sim runs) is a Scout tab, not a
 * top-level nav item: it answers the same question as the leaderboard
 * (who should I copy?) with your own equity and top-N.
 */
export const SCOUT_TABS = [
  { href: "/scout", label: "Leaderboard" },
  { href: "/discover", label: "Custom sim" },
] as const;

export type ScoutTabHref = (typeof SCOUT_TABS)[number]["href"];

/** The active Scout tab for a pathname, or null off the two tab pages (trader detail /scout/0x... has no tabs). */
export function scoutTabFor(pathname: string | null): ScoutTabHref | null {
  if (pathname === "/scout") return "/scout";
  if (pathname === "/discover" || pathname?.startsWith("/discover/")) return "/discover";
  return null;
}

/** The top-level Scout item is active on /scout, its sub-pages, and /discover. */
export function isScoutSection(pathname: string | null): boolean {
  if (!pathname) return false;
  return pathname === "/scout" || pathname.startsWith("/scout/") || scoutTabFor(pathname) === "/discover";
}
