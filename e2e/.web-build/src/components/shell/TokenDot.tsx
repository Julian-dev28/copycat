import { clsx } from "clsx";

/**
 * API token status dot, shown at every size (UX audit: the "no API token"
 * hint was desktop-only). Never color alone: the parent carries a label.
 */
export function TokenDot({ ok, className }: { ok: boolean; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        "pointer-events-none absolute top-1 right-1 h-2 w-2 rounded-full ring-2 ring-[var(--bg)]",
        ok ? "bg-ok" : "bg-warn",
        className,
      )}
    />
  );
}
