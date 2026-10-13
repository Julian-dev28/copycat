"use client";

import { Suspense } from "react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { clsx } from "clsx";
import { containerClass } from "@/lib/shell/container";
import { OnboardingChecklist } from "./OnboardingChecklist";

/**
 * <main> in the route's container (the header uses the same one). Bottom
 * padding clears the mobile tab bar plus the iOS home indicator. The demo
 * strip lives in the sticky header (TopNav), so it shows on every route.
 * The first-run checklist sits above every page's own content until the
 * user is actually set up (OnboardingChecklist.tsx): token, account,
 * deposit, a trader to copy, trading live.
 */
export function AppMain({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <main
      id="main"
      tabIndex={-1}
      className={clsx(
        containerClass(pathname),
        "flex-1 pt-4 pb-[calc(var(--tabbar-h)+env(safe-area-inset-bottom)+1.5rem)] outline-none sm:pt-6 sm:pb-10",
      )}
    >
      <Suspense fallback={null}>
        <OnboardingChecklist />
      </Suspense>
      {children}
    </main>
  );
}
