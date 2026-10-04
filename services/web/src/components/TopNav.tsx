"use client";

import { BarChart3, CircleUserRound, KeyRound, Moon, Settings as SettingsIcon, Sun, Telescope, Wallet } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useSyncExternalStore, type CSSProperties } from "react";
import { clsx } from "clsx";
import { useAuth } from "@/context/AuthContext";
import { CatLogo } from "@/components/CatLogo";
import { AccountSwitcher } from "@/components/account/AccountSwitcher";
import { isNavActive, NAV_LINKS } from "@/lib/trade/nav";

const ICONS = { "/": BarChart3, "/scout": Telescope, "/portfolio": Wallet, "/account": CircleUserRound, "/settings": SettingsIcon } as const;

/** NAV_LINKS (lib/trade/nav) plus Account, slotted before Settings: Trade · Scout · Portfolio · Account · Settings. */
type Href = keyof typeof ICONS;
const LINKS: { href: Href; label: string }[] = [
  ...NAV_LINKS.filter((l) => l.href !== "/settings"),
  { href: "/account", label: "Account" },
  ...NAV_LINKS.filter((l) => l.href === "/settings"),
];
const isActive = (href: Href, pathname: string | null) =>
  href === "/account" ? Boolean(pathname && (pathname === href || pathname.startsWith(`${href}/`))) : isNavActive(href, pathname);

const noopSubscribe = () => () => {};
const demoQuery = () => {
  const p = new URLSearchParams(window.location.search);
  return p.get("demo") === "1" ? `?demo=1${p.get("acct") ? `&acct=${p.get("acct")}` : ""}` : "";
};

export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { openDrawer, hasToken } = useAuth();
  // false during SSR/hydration, true on the client: the theme icon needs it.
  const mounted = useSyncExternalStore(noopSubscribe, () => true, () => false);
  // Keep demo mode across the nav (read at render; client navigation re-renders the nav).
  const demo = useSyncExternalStore(noopSubscribe, demoQuery, () => "");

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-2 px-4">
        <div className="flex min-w-0 items-center gap-3 sm:gap-6">
          <Link
            href={`/${demo}`}
            aria-label="copycat home"
            className="flex items-center gap-1.5 text-base font-bold tracking-tight"
            // Eyes use the accent's own foreground: near-black on the dark theme's #ff7a1a (7.7:1),
            // near-white on the light theme's #b04a08 (6.2:1). Near-black on #b04a08 is only ~3:1.
            style={{ "--cat-eye": "var(--accent-foreground)" } as CSSProperties}
          >
            <CatLogo size={22} className="text-accent" />
            <span className="hidden min-[420px]:inline">
              <span className="text-accent">copy</span>
              <span>cat</span>
            </span>
          </Link>
          <nav className="flex items-center gap-0.5 sm:gap-1" aria-label="Primary">
            {LINKS.map(({ href, label }) => {
              const Icon = ICONS[href];
              const active = isActive(href, pathname);
              return (
                <Link
                  key={href}
                  href={`${href}${demo}`}
                  aria-current={active ? "page" : undefined}
                  aria-label={label}
                  className={clsx(
                    "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors sm:px-3",
                    active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-foreground",
                  )}
                >
                  <Icon size={15} aria-hidden="true" />
                  <span className={active ? "hidden min-[480px]:inline" : "hidden md:inline"}>{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1 sm:gap-2">
          <Suspense fallback={null}>
            <AccountSwitcher />
          </Suspense>
          {!hasToken && !demo ? <span className="hidden text-xs text-warning lg:inline">no API token set</span> : null}
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={mounted && theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-foreground"
          >
            {mounted && theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <button
            type="button"
            onClick={openDrawer}
            aria-label="API token"
            title="API token"
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-foreground"
          >
            <KeyRound size={17} />
          </button>
        </div>
      </div>
    </header>
  );
}
