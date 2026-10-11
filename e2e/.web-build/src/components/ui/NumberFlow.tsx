"use client";

import { clsx } from "clsx";
import { useState } from "react";
import { useFlashOnChange } from "@/hooks/useFlashOnChange";
import { changedDigits } from "@/lib/display/numberFlow";

/**
 * An animated number change (DESIGN 4: "data is never late"). The new value
 * renders at once; only the characters that changed roll in (4px, --dur-base,
 * from below when the value rose, from above when it fell), and the cell
 * flashes its up/down tint, throttled to once per 2s. No counting from 0.
 * Reduced motion: no roll; the flash becomes a static left tint (globals.css).
 */
export function NumberFlow({
  value,
  format,
  className,
  flash = true,
}: {
  value: number | null | undefined;
  format: (v: number | null | undefined) => string;
  className?: string;
  /** Tint the cell on change (default on). */
  flash?: boolean;
}) {
  const text = format(value);
  const [state, setState] = useState({ text, prev: text, value, dir: 0, version: 0 });
  if (state.text !== text) {
    // adjust state during render (React's documented pattern for "previous value")
    const dir = value != null && state.value != null ? Math.sign(value - state.value) : 0;
    setState({ text, prev: state.text, value, dir, version: state.version + 1 });
  }
  const flashClass = useFlashOnChange(flash ? value : null);
  const changed = changedDigits(state.prev, text);

  return (
    <span className={clsx("font-num inline-flex rounded-sm tabular-nums", flashClass, className)} aria-live="off">
      <span className="sr-only">{text}</span>
      <span aria-hidden="true" className="inline-flex">
        {text.split("").map((ch, i) =>
          changed.has(i) && state.version > 0 ? (
            <span key={`${i}-${state.version}`} className={clsx("nf-digit", state.dir < 0 ? "nf-down" : "nf-up")}>
              {ch}
            </span>
          ) : (
            <span key={i}>{ch}</span>
          ),
        )}
      </span>
    </span>
  );
}
