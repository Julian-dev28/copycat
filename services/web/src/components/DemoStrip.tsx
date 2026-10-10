"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { FlaskConical } from "lucide-react";
import { exitDemoHref, routeHasOwnDemoBanner } from "@/lib/demo/strip";

/**
 * The demo strip for every route that has no banner of its own. Needs a
 * <Suspense> above it (useSearchParams). Writes are blocked in demo by the api
 * client itself (lib/api/client.ts isDemoMode), whatever a page does.
 */
export function DemoStrip() {
  const pathname = usePathname();
  const sp = useSearchParams();
  if (sp.get("demo") !== "1" || routeHasOwnDemoBanner(pathname)) return null;
  return (
    <div
      role="status"
      className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-accent/40 bg-accent-soft/40 px-3 py-1.5 text-xs text-muted"
    >
      <FlaskConical size={13} className="text-accent" aria-hidden="true" />
      <span>
        <span className="font-semibold text-foreground">Demo.</span> Sample data in this tab only. Nothing here reaches your account.
      </span>
      <Link href={exitDemoHref(pathname, sp.toString())} className="ml-auto font-medium text-accent underline-offset-2 hover:underline">
        Leave demo
      </Link>
    </div>
  );
}
