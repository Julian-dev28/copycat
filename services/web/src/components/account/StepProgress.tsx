import { clsx } from "clsx";
import { Check, Loader2, X } from "lucide-react";
import type { SignStepView } from "@/lib/account/signView";

/** Numbered vertical steps with a status icon and a live detail line. */
export function StepProgress({ steps }: { steps: SignStepView[] }) {
  return (
    <ol className="flex flex-col gap-0" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s.title} className="flex gap-3" aria-current={s.state === "doing" ? "step" : undefined}>
          <div className="flex flex-col items-center">
            <span
              className={clsx(
                "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm border text-xs font-semibold",
                s.state === "done" && "border-success bg-success/15 text-success",
                s.state === "doing" && "border-accent bg-accent-soft text-accent",
                s.state === "failed" && "border-danger bg-danger/10 text-danger",
                s.state === "todo" && "border-border text-muted",
              )}
            >
              {s.state === "done" ? <Check size={14} /> : s.state === "doing" ? <Loader2 size={14} className="animate-spin" /> : s.state === "failed" ? <X size={14} /> : i + 1}
            </span>
            {i < steps.length - 1 ? <span className={clsx("my-1 w-px flex-1", s.state === "done" ? "bg-success/50" : "bg-border")} /> : null}
          </div>
          <div className="min-w-0 pb-4">
            <p className={clsx("text-sm font-medium", s.state === "todo" ? "text-muted" : "text-foreground")}>{s.title}</p>
            {s.detail ? <p className={clsx("mt-0.5 text-xs", s.state === "failed" ? "text-danger" : "text-muted")}>{s.detail}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
