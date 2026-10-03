import { AlertTriangle, Check, Loader2 } from "lucide-react";

export type SaveState = "idle" | "saving" | "saved" | "error";

export function SaveStatusBadge({ state, errorMessage }: { state: SaveState; errorMessage?: string | null }) {
  if (state === "idle") return null;
  if (state === "saving") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted" role="status">
        <Loader2 size={13} className="animate-spin" aria-hidden="true" />
        Saving…
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-danger" role="alert">
        <AlertTriangle size={13} aria-hidden="true" />
        {errorMessage ? `Save failed: ${errorMessage}` : "Save failed"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-success" role="status">
      <Check size={13} aria-hidden="true" />
      Saved
    </span>
  );
}
