import { clsx } from "clsx";
import { AlertTriangle, Info, XOctagon } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "warning" | "danger" | "info";

const toneClasses: Record<Tone, string> = {
  warning: "border-warning/40 bg-warning/10",
  danger: "border-danger/40 bg-danger/10",
  info: "border-accent/30 bg-accent-soft",
};

const iconClasses: Record<Tone, string> = {
  warning: "text-warning",
  danger: "text-danger",
  info: "text-accent",
};

/** Page-level banner: icon, bold title, body. Used for the empty-account and api-error states. */
export function Notice({
  tone = "warning",
  title,
  children,
  action,
  className,
}: {
  tone?: Tone;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = tone === "danger" ? XOctagon : tone === "info" ? Info : AlertTriangle;
  return (
    <div
      role={tone === "info" ? "status" : "alert"}
      className={clsx("flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-start sm:px-5", toneClasses[tone], className)}
    >
      <Icon size={18} className={clsx("mt-0.5 flex-shrink-0", iconClasses[tone])} aria-hidden="true" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-foreground">{title}</p>
        {children ? <div className="mt-1 text-muted">{children}</div> : null}
      </div>
      {action ? <div className="flex-shrink-0">{action}</div> : null}
    </div>
  );
}
