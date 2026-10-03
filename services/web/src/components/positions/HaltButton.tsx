"use client";

import { Octagon } from "lucide-react";
import { useHaltEngine } from "@/hooks/useEngineStatus";

export function HaltButton() {
  const halt = useHaltEngine();

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => halt.mutate()}
        disabled={halt.isPending}
        aria-label="Halt engine: stop opening or adding to new copies"
        className="flex items-center gap-2 rounded-xl border-2 border-danger bg-danger/10 px-5 py-3 text-base font-bold text-danger transition-colors hover:bg-danger hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        <Octagon size={20} aria-hidden="true" />
        {halt.isPending ? "Halting…" : "Halt"}
      </button>
      <p className="max-w-[16rem] text-right text-xs text-muted">
        Flips trading off. Existing positions keep mirroring exits.
      </p>
      {halt.isError ? <p className="text-xs text-danger">{halt.error.message}</p> : null}
    </div>
  );
}
