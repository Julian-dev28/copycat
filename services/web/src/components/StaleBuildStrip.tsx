"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { clsx } from "clsx";
import { api } from "@/lib/api/client";
import { containerClass } from "@/lib/shell/container";
import { staleBuildText } from "@/lib/shell/staleBuild";

/**
 * Version-skew strip (audit M12), pinned under the header next to the demo
 * strip: shown while GET /api/health says a process runs other code than
 * the api. Off in demo (no api). Health needs no token.
 */
export function StaleBuildStrip() {
  const pathname = usePathname();
  const demo = useSearchParams().get("demo") === "1";
  const q = useQuery({ queryKey: ["health"], queryFn: api.health, enabled: !demo, refetchInterval: 30_000, retry: false });
  const text = demo ? null : staleBuildText(q.data);
  if (!text) return null;
  return (
    <div role="status" className="border-t border-warn/25 bg-warn-soft">
      <div className={clsx(containerClass(pathname), "flex min-h-8 items-center gap-2 py-1 text-xs text-fg-soft")}>
        <RefreshCw size={13} className="flex-shrink-0 text-warn" aria-hidden="true" />
        <p className="min-w-0 flex-1">{text}</p>
      </div>
    </div>
  );
}
