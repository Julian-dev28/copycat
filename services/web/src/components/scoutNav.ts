/**
 * Scout is one page now (contract v16 retired /discover, the "Custom sim"
 * tab: the board's own sim terms toolbar replaces it). This is just the
 * top-level nav item's active-section check, kept as its own module since
 * lib/shell/nav.ts imports it and /scout/0x... (the trader file) must count
 * as the same section.
 */
export function isScoutSection(pathname: string | null): boolean {
  if (!pathname) return false;
  return pathname === "/scout" || pathname.startsWith("/scout/");
}
