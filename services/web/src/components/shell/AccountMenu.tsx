"use client";

import Link from "next/link";
import { KeyRound, Menu, Moon, Settings, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useId, useRef } from "react";
import { useAuth } from "@/context/AuthContext";
import { LABELS } from "@/lib/labels";
import { TokenDot } from "./TokenDot";
import { useDemoQuery, useMounted } from "./useDemoQuery";

const ITEM =
  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-fg-soft transition-colors duration-[var(--dur-fast)] hover:bg-surface-2 hover:text-fg";

/**
 * Mobile (< sm) account menu: Settings, theme and API token, which the
 * desktop header shows inline. Native popover: Esc and outside click close it.
 */
export function AccountMenu() {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const { openDrawer, hasToken } = useAuth();
  const demo = useDemoQuery();
  const mounted = useMounted();
  const tokenOk = hasToken || Boolean(demo);
  const close = () => ref.current?.hidePopover?.();

  return (
    <>
      <button
        type="button"
        popoverTarget={id}
        aria-label={`${LABELS.accountMenu}${tokenOk ? "" : `, ${LABELS.noApiToken.toLowerCase()}`}`}
        className="relative grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-fg sm:hidden"
      >
        <Menu size={18} aria-hidden="true" />
        {mounted ? <TokenDot ok={tokenOk} /> : null}
      </button>
      <div
        ref={ref}
        id={id}
        popover="auto"
        className="menu-pop m-0 w-56 rounded-2xl border border-border bg-surface-3 p-1.5 text-fg shadow-e2"
      >
        <Link href={`/settings${demo}`} onClick={close} className={ITEM}>
          <Settings size={16} aria-hidden="true" /> {LABELS.nav.settings}
        </Link>
        <button
          type="button"
          className={ITEM}
          onClick={() => {
            setTheme(theme === "dark" ? "light" : "dark");
            close();
          }}
        >
          {mounted && theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
          {mounted && theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
        <button
          type="button"
          className={ITEM}
          onClick={() => {
            close();
            openDrawer();
          }}
        >
          <KeyRound size={16} aria-hidden="true" />
          <span className="flex-1">{LABELS.apiToken}</span>
          <span className={tokenOk ? "text-label text-ok" : "text-label text-warn"}>{tokenOk ? "Set" : "Missing"}</span>
        </button>
      </div>
    </>
  );
}
