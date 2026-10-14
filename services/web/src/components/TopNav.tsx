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
import { StaleBuildStrip } from "@/components/StaleBuildStrip";
import { NAV_ICONS } from "@/components/shell/navIcons";
import { ScrollProgress } from "@/components/shell/ScrollProgress";
import { TokenDot } from "@/components/shell/TokenDot";
import { useDemoQuery, useMounted } from "@/components/shell/useDemoQuery";
import { LABELS } from "@/lib/labels";
import { containerClass } from "@/lib/shell/container";
import { isItemActive, NAV_ITEMS } from "@/lib/shell/nav";

const ICON_BTN =
  "relative grid h-9 w-9 place-items-center rounded-sm text-muted transition-colors duration-[var(--dur-fast)] hover:bg-surface-2 hover:text-fg";

/**
 * Sticky glass header (DESIGN.md 6, v2 "terminal"): cat + wordmark (brand
 * ember), the primary nav as flat mono uppercase links with a 1px accent
 * underline on the active one (sm and up; phones use BottomTabBar), then the
 * account chip, theme and API token. A scroll-progress hairline runs along
 * the bottom edge. Same container as <main>.
 */
export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { openDrawer, hasToken } = useAuth();
  const mounted = useMounted();
  const demo = useDemoQuery();
  const tokenOk = hasToken || Boolean(demo);

  return (
    <header className="vt-header sticky top-0 z-40 border-b border-border bg-[var(--glass-bg)] shadow-[inset_0_1px_0_rgb(255_255_255/0.04)] backdrop-blur-xl backdrop-saturate-150">
      <div className={clsx(containerClass(pathname), "flex h-14 items-center justify-between gap-2")}>
        <div className="flex min-w-0 items-center gap-4 self-stretch lg:gap-6">
          <Link
            href={`/${demo}`}
            aria-label="copycat home"
            className="flex flex-shrink-0 items-center gap-1.5 rounded-sm text-base font-semibold tracking-tight"
            style={{ "--cat-eye": "var(--brand-fg)" } as CSSProperties}
          >
            <CatLogo size={24} className="text-brand" />
            <span>
              <span className="text-brand">copy</span>
              <span className="text-fg">cat</span>
            </span>
          </Link>
          <nav aria-label="Primary" className="hidden items-stretch gap-1 self-stretch sm:flex">
            {NAV_ITEMS.map(({ href, label }) => {
              const Icon = NAV_ICONS[href];
              const active = isItemActive(href, pathname);
              return (
                <Link
                  key={href}
                  href={`${href}${demo}`}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "relative flex items-center gap-1.5 px-3 font-mono text-[11px] font-medium tracking-[0.14em] uppercase transition-colors duration-[var(--dur-fast)]",
                    active ? "text-fg" : "text-muted hover:text-fg",
                  )}
                >
                  <Icon size={14} aria-hidden="true" className="md:hidden" />
                  <span className="hidden md:inline">{label}</span>
                  <span className="sr-only md:hidden">{label}</span>
                  {active ? (
                    <span
                      aria-hidden="true"
                      className="absolute inset-x-3 -bottom-px h-px bg-accent"
                      style={{ viewTransitionName: "nav-pill" }}
                    />
                  ) : null}
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
      <Suspense fallback={null}>
        <DemoStrip />
        <StaleBuildStrip />
      </Suspense>
      <ScrollProgress />
    </header>
  );
}
