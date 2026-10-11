"use client";

import { KeyRound, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, type CSSProperties } from "react";
import { clsx } from "clsx";
import { useAuth } from "@/context/AuthContext";
import { CatLogo } from "@/components/CatLogo";
import { AccountSwitcher } from "@/components/account/AccountSwitcher";
import { AccountMenu } from "@/components/shell/AccountMenu";
import { DemoStrip } from "@/components/DemoStrip";
import { NAV_ICONS } from "@/components/shell/navIcons";
import { TokenDot } from "@/components/shell/TokenDot";
import { useDemoQuery, useMounted } from "@/components/shell/useDemoQuery";
import { SCOUT_TABS, scoutTabFor } from "@/components/scoutNav";
import { LABELS } from "@/lib/labels";
import { containerClass } from "@/lib/shell/container";
import { isItemActive, NAV_ITEMS } from "@/lib/shell/nav";

const ICON_BTN =
  "relative grid h-9 w-9 place-items-center rounded-full text-muted transition-colors duration-[var(--dur-fast)] hover:bg-surface-2 hover:text-fg";

/**
 * Sticky glass header (DESIGN.md 6): cat + wordmark (brand ember), the
 * primary nav as a pill group (sm and up; phones use BottomTabBar), then the
 * account chip, theme and API token. Same container as <main>.
 */
export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { openDrawer, hasToken } = useAuth();
  const mounted = useMounted();
  const demo = useDemoQuery();
  const tokenOk = hasToken || Boolean(demo);

  return (
    <header className="vt-header sticky top-0 z-40 border-b border-border bg-[var(--glass-bg)] backdrop-blur-xl backdrop-saturate-150">
      <div className={clsx(containerClass(pathname), "flex h-14 items-center justify-between gap-2")}>
        <div className="flex min-w-0 items-center gap-4 lg:gap-6">
          <Link
            href={`/${demo}`}
            aria-label="copycat home"
            className="flex flex-shrink-0 items-center gap-1.5 rounded-full text-base font-semibold tracking-tight"
            style={{ "--cat-eye": "var(--brand-fg)" } as CSSProperties}
          >
            <CatLogo size={24} className="text-brand" />
            <span>
              <span className="text-brand">copy</span>
              <span className="text-fg">cat</span>
            </span>
          </Link>
          <nav aria-label="Primary" className="hidden items-center gap-0.5 rounded-full border border-border bg-surface-2/60 p-1 sm:flex">
            {NAV_ITEMS.map(({ href, label }) => {
              const Icon = NAV_ICONS[href];
              const active = isItemActive(href, pathname);
              return (
                <Link
                  key={href}
                  href={`${href}${demo}`}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "relative flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors duration-[var(--dur-fast)]",
                    active ? "text-fg" : "text-muted hover:text-fg",
                  )}
                >
                  {active ? (
                    <span
                      aria-hidden="true"
                      className="absolute inset-0 rounded-full bg-surface shadow-e1 dark:bg-surface-3"
                      style={{ viewTransitionName: "nav-pill" }}
                    />
                  ) : null}
                  <Icon size={15} aria-hidden="true" className="relative" />
                  <span className="relative hidden md:inline">{label}</span>
                  <span className="sr-only md:hidden">{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex min-w-0 flex-shrink items-center gap-1 sm:gap-1.5">
          <Suspense fallback={null}>
            <AccountSwitcher />
          </Suspense>
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={mounted && theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className={clsx(ICON_BTN, "hidden sm:grid")}
          >
            {mounted && theme === "dark" ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={openDrawer}
            aria-label={`${LABELS.apiToken}: ${tokenOk ? "set" : "missing"}`}
            title={tokenOk ? LABELS.apiTokenSet : LABELS.noApiToken}
            className={clsx(ICON_BTN, "hidden sm:grid")}
          >
            <KeyRound size={17} aria-hidden="true" />
            {mounted ? <TokenDot ok={tokenOk} /> : null}
          </button>
          <AccountMenu />
        </div>
      </div>
      <ScoutTabs pathname={pathname} demo={demo} />
      <Suspense fallback={null}>
        <DemoStrip />
      </Suspense>
    </header>
  );
}

/** Second row on /scout and /discover so the custom sim is one click from the leaderboard, and back. */
function ScoutTabs({ pathname, demo }: { pathname: string | null; demo: string }) {
  const activeTab = scoutTabFor(pathname);
  if (!activeTab) return null;
  return (
    <nav aria-label="Scout" className={clsx(containerClass(pathname), "flex items-center gap-1 pb-2")}>
      {SCOUT_TABS.map(({ href, label }) => {
        const active = href === activeTab;
        return (
          <Link
            key={href}
            href={`${href}${demo}`}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors duration-[var(--dur-fast)] sm:text-sm",
              active ? "bg-surface-3 text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
