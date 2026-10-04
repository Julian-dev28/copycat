import { clsx } from "clsx";
import type { ReactNode } from "react";
import { formatSignedPct } from "@/lib/format";

/** "+4.2%" green / "-1.3%" red / "n/a" muted. */
export function ChangeText({ pct, className, digits = 2 }: { pct: number | null | undefined; className?: string; digits?: number }) {
  const ok = pct !== null && pct !== undefined && Number.isFinite(pct);
  return (
    <span className={clsx("font-num", !ok ? "text-muted" : pct > 0 ? "text-success" : pct < 0 ? "text-danger" : "text-muted", className)}>
      {ok ? formatSignedPct(pct, Math.abs(pct) >= 100 ? 0 : digits) : "n/a"}
    </span>
  );
}

/** Signed USD with tone. */
export function PnlText({ usd, children, className }: { usd: number | null | undefined; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("font-num", !usd ? "text-muted" : usd > 0 ? "text-success" : "text-danger", className)}>{children}</span>
  );
}

/** Small label + value pair for header stats. */
export function Stat({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={clsx("flex flex-col", className)}>
      <span className="text-[11px] uppercase tracking-wide text-muted">{label}</span>
      <span className="text-sm">{children}</span>
    </div>
  );
}

/** Keep `?demo=1&acct=` on internal links while in demo mode. */
export function withDemo(path: string, demo: boolean, acct?: string): string {
  if (!demo) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}demo=1${acct && acct !== "default" ? `&acct=${acct}` : ""}`;
}
