"use client";

import { Copy, Gauge, Moon, Radar, Settings as SettingsIcon, Sun, Telescope } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { clsx } from "clsx";
import { useAuth } from "@/context/AuthContext";

const LINKS = [
  { href: "/scout", label: "Scout", icon: Telescope },
  { href: "/copy", label: "Copy", icon: Copy },
  { href: "/positions", label: "Positions", icon: Gauge },
  { href: "/discover", label: "Discover", icon: Radar },
];

const noopSubscribe = () => () => {};

export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { openDrawer, hasToken } = useAuth();
  // false during SSR/hydration, true on the client: the theme icon needs it.
  const mounted = useSyncExternalStore(noopSubscribe, () => true, () => false);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-2 px-4">
        <div className="flex min-w-0 items-center gap-3 sm:gap-6">
          <Link href="/copy" className="flex items-center gap-1.5 text-base font-bold tracking-tight">
            <span className="text-accent">copy</span>
            <span>cat</span>
          </Link>
          <nav className="flex items-center gap-0.5 sm:gap-1" aria-label="Primary">
            {LINKS.map(({ href, label, icon: Icon }) => {
              const active = pathname?.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  aria-label={label}
                  className={clsx(
                    "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors sm:px-3",
                    active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-foreground",
                  )}
                >
                  <Icon size={15} aria-hidden="true" />
                  <span className={active ? "" : "hidden sm:inline"}>{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1 sm:gap-2">
          {!hasToken ? (
            <span className="hidden text-xs text-warning sm:inline">no API token set</span>
          ) : null}
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
            aria-label="Open settings"
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-foreground"
          >
            <SettingsIcon size={17} />
          </button>
        </div>
      </div>
    </header>
  );
}
