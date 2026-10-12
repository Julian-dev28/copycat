"use client";

import { useId, useState, type FocusEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { AlertTriangle, Info } from "lucide-react";
import { blendedFit, capLines, fitGrade, fitPartsLine, fitSegments, fitTier, type FitGrade, type FitTier } from "@/lib/scout/copyFit";
import type { CopyFit } from "@/lib/scout/types";

const GRADE_TEXT: Record<FitGrade, string> = { strong: "strong", fair: "fair", weak: "weak", none: "not scored" };

/**
 * Single-hue accent ramp by bucket (DESIGN 3.4: 90+, 70 to 89, 50 to 69,
 * below 50). A score is a ranking, not money: never up/down colors, and the
 * number itself stays --fg (the accent never colors a number).
 */
const TIER_FILL: Record<FitTier, string> = {
  3: "var(--accent)",
  2: "color-mix(in srgb, var(--accent) 78%, var(--surface-3))",
  1: "color-mix(in srgb, var(--accent) 56%, var(--surface-3))",
  0: "color-mix(in srgb, var(--accent) 36%, var(--surface-3))",
};

/**
 * Copy Fit bar: one slot per part, each slot as wide as the part's weight,
 * filled to the part's 0..1 value. Total filled area = the pre-cap blend,
 * so the bar *is* the formula. 2px gaps between slots.
 */
export function FitBar({ fit, className, height = 8 }: { fit: CopyFit; className?: string; height?: number }) {
  const segs = fitSegments(fit);
  const fill = TIER_FILL[fitTier(fit.value) ?? 0];
  return (
    <div className={clsx("flex w-full gap-[2px]", className)} style={{ height }} aria-hidden="true">
      {segs.map((s) => (
        <div key={s.key} className="relative overflow-hidden rounded-[2px] bg-surface-3" style={{ width: `${s.max}%` }}>
          <div className="absolute inset-y-0 left-0" style={{ width: `${s.part * 100}%`, background: fill }} />
        </div>
      ))}
    </div>
  );
}

function Breakdown({ fit }: { fit: CopyFit }) {
  const segs = fitSegments(fit);
  const caps = capLines(fit);
  const blend = blendedFit(fit);
  return (
    <div className="flex flex-col gap-3 text-xs">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-heading text-fg">
          Why Copy Fit <span className="font-num">{Math.round(fit.value)}</span>
        </span>
        <span className="text-label text-muted">of {fit.cohort_size}</span>
      </div>
      <table className="w-full border-separate border-spacing-0">
        <thead>
          <tr>
            <th className="pb-1.5 text-left text-label font-medium text-muted">Part</th>
            <th className="pb-1.5 text-right text-label font-medium text-muted">Rank</th>
            <th className="pb-1.5 text-right text-label font-medium text-muted">Weight</th>
            <th className="pb-1.5 text-right text-label font-medium text-muted">Points</th>
          </tr>
        </thead>
        <tbody className="font-num">
          {segs.map((s) => (
            <tr key={s.key} title={s.hint}>
              <td className="border-t border-border py-1 pr-2 font-sans text-fg-soft">{s.label}</td>
              <td className="border-t border-border py-1 text-right text-muted">{Math.round(s.part * 100)}</td>
              <td className="border-t border-border py-1 text-right text-muted">{Math.round(s.weight * 100)}%</td>
              <td className="border-t border-border py-1 text-right text-fg">{s.points.toFixed(1)}</td>
            </tr>
          ))}
          <tr>
            <td className="border-t border-border-strong py-1 font-sans text-muted" colSpan={3}>
              Blend, before caps
            </td>
            <td className="border-t border-border-strong py-1 text-right font-medium text-fg">{blend.toFixed(1)}</td>
          </tr>
        </tbody>
      </table>
      {caps.length ? (
        <ul className="flex flex-col gap-1">
          {caps.map((c) => (
            <li key={c.flag} className={clsx("flex gap-1.5", c.binding ? "text-warn" : "text-muted")}>
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
              <span>
                {c.text}
                {c.binding ? "." : " (not binding)."}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-[11px] leading-snug text-muted">
        Each part is a percentile rank in this refresh&apos;s cohort, except sample, capacity and recency. &quot;Your copy&quot; is the sim at your
        saved settings, so it moves when they do. Points add up to 100.
      </p>
    </div>
  );
}

const POP_W = 304;

/**
 * Copy Fit number + bar, with the breakdown on hover, focus or tap. The
 * popover is fixed-positioned in a portal so a scrolling table or a card
 * edge can't clip it; it is placed from the trigger's rect at open time.
 */
export function CopyFitMeter({
  fit,
  size = "sm",
  showParts = true,
  className,
}: {
  fit: CopyFit | null | undefined;
  size?: "sm" | "lg";
  /** The "points" line under the bar (cards); off in the dense table. */
  showParts?: boolean;
  className?: string;
}) {
  const [pos, setPos] = useState<{ left: number; top: number; above: boolean } | null>(null);
  const [pinned, setPinned] = useState(false);
  const popId = useId();
  const grade = fitGrade(fit?.value);

  function open(e: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - POP_W / 2), Math.max(8, vw - POP_W - 8));
    const above = r.bottom + 380 > vh && r.top > 380;
    setPos({ left, top: above ? r.top - 8 : r.bottom + 8, above });
  }
  function close() {
    if (!pinned) setPos(null);
  }

  if (!fit) {
    return (
      <div className={clsx("flex items-center gap-2 text-xs text-muted", className)}>
        <span className="font-num text-sm">—</span> Copy Fit not scored yet
      </div>
    );
  }

  const big = size === "lg";
  const capped = fit.caps.some((c) => c !== "fills_truncated");
  return (
    <div className={clsx("min-w-0", className)}>
      <button
        type="button"
        className="group flex w-full cursor-help flex-col gap-1.5 rounded-lg text-left"
        aria-describedby={pos ? popId : undefined}
        aria-label={`Copy Fit ${Math.round(fit.value)} of 100, ${GRADE_TEXT[grade]}. Show breakdown`}
        onMouseEnter={open}
        onMouseLeave={close}
        onFocus={open}
        onBlur={() => {
          setPinned(false);
          setPos(null);
        }}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          if (pinned) {
            setPinned(false);
            setPos(null);
          } else {
            open(e);
            setPinned(true);
          }
        }}
      >
        <span className="flex items-baseline gap-1.5">
          <span className={clsx("text-fg", big ? "num-xl" : "num-lg leading-none")}>{Math.round(fit.value)}</span>
          <span className="num-sm text-muted">/100</span>
          <span className="ml-auto inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-medium text-muted group-hover:text-fg-soft">
            {capped ? <AlertTriangle size={11} className="text-warn" aria-hidden="true" /> : null}
            {showParts ? "Copy Fit · " : ""}
            {GRADE_TEXT[grade]}
            <Info size={11} className="opacity-60 group-hover:opacity-100" aria-hidden="true" />
          </span>
        </span>
        <FitBar fit={fit} height={big ? 8 : 6} />
        {showParts ? <span className="truncate text-[11px] text-muted">{fitPartsLine(fit)}</span> : null}
      </button>
      {pos
        ? createPortal(
            <div
              id={popId}
              role="tooltip"
              className="fixed z-50 rounded-xl border border-border bg-surface-3 p-4 shadow-e2"
              style={{ left: pos.left, top: pos.top, width: POP_W, transform: pos.above ? "translateY(-100%)" : undefined }}
            >
              <Breakdown fit={fit} />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
