"use client";

import { Octagon, PauseCircle } from "lucide-react";
import { useHaltEngine } from "@/hooks/useEngineStatus";

/** Big red stop. Once trading is already off it collapses to a quiet "paused" state instead of shouting. */
export function HaltButton({ enabled }: { enabled?: boolean }) {
  const halt = useHaltEngine();
  const alreadyOff = enabled === false;

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      {alreadyOff ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm font-semibold text-muted"
        >
          <PauseCircle size={18} aria-hidden="true" />
          Trading is off
        </div>
      ) : (
        <button
          type="button"
          onClick={() => halt.mutate()}
          disabled={halt.isPending || enabled === undefined}
          aria-label="Halt engine: stop opening or adding to new copies"
          className="flex items-center gap-2 rounded-xl border-2 border-danger bg-danger/10 px-5 py-2.5 text-base font-bold text-danger transition-colors hover:bg-danger hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Octagon size={20} aria-hidden="true" />
          {halt.isPending ? "Halting…" : "Halt"}
        </button>
      )}
      <p className="max-w-[11rem] text-xs text-muted sm:max-w-[16rem] sm:text-right">
        {alreadyOff ? "Turn it on from /copy. Exits still mirror." : "Stops new copies. Exits keep mirroring."}
      </p>
      {halt.isError ? <p className="text-xs text-danger">{halt.error.message}</p> : null}
    </div>
  );
}
