"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import { isItemActive, MOBILE_TABS } from "@/lib/shell/nav";
import { NAV_ICONS } from "./navIcons";
import { useDemoQuery } from "./useDemoQuery";

/**
 * Phones (< sm): labeled bottom tabs, Trade · Scout · Portfolio · Account.
 * Settings, theme and API token live in the header's AccountMenu.
 */
export function BottomTabBar() {
  const pathname = usePathname();
  const demo = useDemoQuery();
  return (
    <nav
      aria-label="Primary"
      className="vt-tabbar fixed inset-x-0 bottom-0 z-40 border-t border-border bg-[var(--glass-bg)] pb-[env(safe-area-inset-bottom)] backdrop-blur-xl backdrop-saturate-150 sm:hidden"
    >
      <ul className="grid h-[var(--tabbar-h)] grid-cols-4">
        {MOBILE_TABS.map(({ href, label }) => {
          const Icon = NAV_ICONS[href];
          const active = isItemActive(href, pathname);
          return (
            <li key={href} className="flex">
              <Link
                href={`${href}${demo}`}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-[var(--dur-fast)] focus-visible:-outline-offset-4",
                  active ? "text-accent" : "text-muted hover:text-fg",
                )}
              >
                <span className={clsx("grid h-7 w-12 place-items-center rounded-sm transition-colors", active && "bg-accent-soft")}>
                  <Icon size={18} aria-hidden="true" />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
