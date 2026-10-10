/**
 * Which routes draw their own demo banner (Trade has the account switch, Scout
 * and the trader file their own). Every other route gets the shared DemoStrip,
 * so no page in demo mode looks like the live app (UX audit #1).
 */
export function routeHasOwnDemoBanner(pathname: string | null): boolean {
  if (!pathname) return false;
  return pathname === "/" || pathname === "/scout" || pathname.startsWith("/scout/");
}

/** The same URL with demo mode (and its demo-only params) removed. */
export function exitDemoHref(pathname: string | null, search: string): string {
  const p = new URLSearchParams(search);
  p.delete("demo");
  p.delete("acct");
  const qs = p.toString();
  return `${pathname || "/"}${qs ? `?${qs}` : ""}`;
}
