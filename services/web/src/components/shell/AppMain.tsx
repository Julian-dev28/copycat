"use client";

import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import { clsx } from "clsx";
import { containerClass } from "@/lib/shell/container";
import { DemoStrip } from "@/components/DemoStrip";

/**
 * <main> in the route's container (the header uses the same one). Bottom
 * padding clears the mobile tab bar plus the iOS home indicator.
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
        <DemoStrip />
      </Suspense>
      {children}
    </main>
  );
}
