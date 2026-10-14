/**
 * The app's navigation model (DESIGN.md 6 "Global shell"): one list for the
 * desktop top nav, a subset for the mobile bottom tab bar (Settings moves
 * into the account menu there). Pure, unit-tested.
 */
import { LABELS } from "@/lib/labels";
import { isNavActive } from "@/lib/trade/nav";
import { isScoutSection } from "@/components/scoutNav";

export type NavHref = "/" | "/scout" | "/portfolio" | "/account" | "/settings";

export interface NavItem {
  href: NavHref;
  label: string;
  /** Shown in the mobile bottom tab bar. */
  mobile: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: LABELS.nav.trade, mobile: true },
  { href: "/scout", label: LABELS.nav.scout, mobile: true },
  { href: "/portfolio", label: LABELS.nav.portfolio, mobile: true },
  { href: "/account", label: LABELS.nav.account, mobile: true },
  { href: "/settings", label: LABELS.nav.settings, mobile: false },
];

export const MOBILE_TABS = NAV_ITEMS.filter((i) => i.mobile);

export function isItemActive(href: NavHref, pathname: string | null): boolean {
  if (!pathname) return false;
  if (href === "/account") return pathname === href || pathname.startsWith(`${href}/`);
  if (href === "/scout") return isScoutSection(pathname);
  return isNavActive(href, pathname);
}

/**
 * The query to carry across nav links: demo mode and its account size only,
 * so the demo strip shows on every route and nothing else leaks between pages.
 */
export function demoQuery(search: string): string {
  const p = new URLSearchParams(search);
  if (p.get("demo") !== "1") return "";
  const acct = p.get("acct");
  return `?demo=1${acct ? `&acct=${encodeURIComponent(acct)}` : ""}`;
}
