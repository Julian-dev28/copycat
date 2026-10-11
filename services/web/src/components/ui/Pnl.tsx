import { clsx } from "clsx";
import { PNL_GLYPH, PNL_TEXT_CLASS, pnlTone } from "@/lib/display/pnlMode";
import { formatSignedPct, formatSignedUsd } from "@/lib/format";

/**
 * Signed money (DESIGN 3.3): color from the user's PnL mode (text-up /
 * text-down, remapped by data-pnl), and never color alone: the text always
 * carries its sign, and `arrow` adds ▲/▼ (summary tiles). Screen readers get
 * "up"/"down" words. Zero, null and NaN render muted.
 */
export function Pnl({
  value,
  format = "usd",
  digits,
  arrow = false,
  className,
  children,
}: {
  value: number | null | undefined;
  format?: "usd" | "pct" | ((v: number) => string);
  digits?: number;
  /** Prefix ▲/▼. Use in tiles and headlines; tables keep the sign only. */
  arrow?: boolean;
  className?: string;
  /** Override the rendered text (already signed); color and arrow still follow `value`. */
  children?: React.ReactNode;
}) {
  const tone = pnlTone(value);
  const ok = value != null && Number.isFinite(value);
  const text = children ?? (!ok ? "n/a" : typeof format === "function" ? format(value) : format === "pct" ? formatSignedPct(value, digits) : formatSignedUsd(value));
  return (
    <span className={clsx("font-num whitespace-nowrap tabular-nums", PNL_TEXT_CLASS[tone], className)}>
      {arrow && PNL_GLYPH[tone] ? (
        <span aria-hidden="true" className="mr-1 inline-block text-[0.75em]">
          {PNL_GLYPH[tone]}
        </span>
      ) : null}
      {tone !== "flat" ? <span className="sr-only">{tone === "up" ? "up " : "down "}</span> : null}
      {text}
    </span>
  );
}
