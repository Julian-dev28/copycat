import { RotateCcw } from "lucide-react";

/**
 * Per-field marker for a custom wallet: "global" when the field follows the
 * Settings tab, or an "inherit" reset when this wallet overrides it.
 */
export function Inherit({ set, onReset, label }: { set: boolean; onReset: () => void; label: string }) {
  if (!set) return <span className="text-[10px] font-medium uppercase tracking-wide text-muted">global</span>;
  return (
    <button
      type="button"
      onClick={onReset}
      title={`${label}: follow the Settings tab again`}
      aria-label={`Inherit ${label} from Settings`}
      className="inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-medium uppercase tracking-wide text-accent hover:bg-accent-soft"
    >
      <RotateCcw size={10} aria-hidden="true" /> inherit
    </button>
  );
}
