"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { FlaskConical } from "lucide-react";
import { clsx } from "clsx";
import { exitDemoHref } from "@/lib/demo/strip";
import { LABELS } from "@/lib/labels";
import { containerClass } from "@/lib/shell/container";

/**
 * The demo strip: a slim --warn-soft row pinned under the header on EVERY
 * route while ?demo=1 is on (UX audit #1, DESIGN.md 6). Rendered inside the
 * sticky header, under a <Suspense> (useSearchParams). Writes are blocked in
 * demo by the api client itself (lib/api/client.ts), whatever a page does.
 */
export function DemoStrip() {
  const pathname = usePathname();
  const sp = useSearchParams();
  if (sp.get("demo") !== "1") return null;
  return (
    <div role="status" className="border-t border-warn/25 bg-warn-soft">
      <div className={clsx(containerClass(pathname), "flex min-h-8 items-center gap-2 py-1 text-xs text-fg-soft")}>
        <FlaskConical size={13} className="flex-shrink-0 text-warn" aria-hidden="true" />
        <p className="min-w-0 flex-1 truncate">
          <span className="font-semibold text-warn">{LABELS.demo}.</span> {LABELS.demoStrip}
        </p>
        <Link
          href={exitDemoHref(pathname, sp.toString())}
          className="flex-shrink-0 rounded-full px-2 py-0.5 font-medium text-warn underline-offset-2 hover:underline"
        >
          {LABELS.leaveDemo}
        </Link>
      </div>
    </div>
  );
}
