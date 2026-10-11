/** Primary nav: Trade is home ("/"). /discover stays reachable from Scout, off the nav. */
export const NAV_LINKS = [
  { href: "/", label: "Trade" },
  { href: "/scout", label: "Scout" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/settings", label: "Settings" },
] as const;

export type NavHref = (typeof NAV_LINKS)[number]["href"];

/** "/" is active only on the home page; other links also on their sub-pages (/scout/0x...). */
export function isNavActive(href: NavHref, pathname: string | null): boolean {
  if (!pathname) return false;
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
