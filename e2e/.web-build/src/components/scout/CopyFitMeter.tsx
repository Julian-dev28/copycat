"use client";

import { useId, useState, type FocusEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { AlertTriangle, Info } from "lucide-react";
import { capLines, fitGrade, fitSegments, blendedFit, topParts, type FitGrade } from "@/lib/scout/copyFit";
import type { CopyFit } from "@/lib/scout/types";

const GRADE_TEXT: Record<FitGrade, string> = { strong: "strong", fair: "fair", weak: "weak", none: "not scored" };

/**
 * Copy Fit bar: one slot per part, each slot as wide as the part's weight,
 * filled to the part's 0..1 value. Total filled area = the pre-cap blend,
 * so the bar *is* the formula. Single hue (magnitude), 2px gaps.
 */
export function FitBar({ fit, className, height = 8 }: { fit: CopyFit; className?: string; height?: number }) {
  const segs = fitSegments(fit);
  return (
    <div className={clsx("flex w-full gap-[2px]", className)} style={{ height }} aria-hidden="true">
      {segs.map((s) => (
        <div key={s.key} className="relative overflow-hidden rounded-[2px] bg-surface-2 ring-1 ring-inset ring-border/60" style={{ width: `${s.max}%` }}>
          <div className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${s.part * 100}%` }} />
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
        <span className="font-semibold text-foreground">Why Copy Fit {Math.round(fit.value)}</span>
        <span className="text-muted">ranked among {fit.cohort_size}</span>
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-muted">
            <th className="pb-1 text-left font-medium">Part</th>
            <th className="pb-1 text-right font-medium">Score</th>
            <th className="pb-1 text-right font-medium">Weight</th>
            <th className="pb-1 text-right font-medium">Adds</th>
          </tr>
        </thead>
        <tbody className="font-num">
          {segs.map((s) => (
            <tr key={s.key} title={s.hint} className="border-t border-border/60">
              <td className="py-1 pr-2 font-sans text-foreground">{s.label}</td>
              <td className="py-1 text-right text-muted">{Math.round(s.part * 100)}</td>
              <td className="py-1 text-right text-muted">{Math.round(s.weight * 100)}%</td>
              <td className="py-1 text-right font-medium text-foreground">{s.points.toFixed(1)}</td>
            </tr>
          ))}
          <tr className="border-t border-border">
            <td className="py-1 font-sans text-muted" colSpan={3}>
              Blend
            </td>
            <td className="py-1 text-right font-semibold text-foreground">{blend.toFixed(1)}</td>
          </tr>
        </tbody>
      </table>
      {caps.length ? (
        <ul className="flex flex-col gap-1">
          {caps.map((c) => (
            <li key={c.flag} className={clsx("flex gap-1.5", c.binding ? "text-warning" : "text-muted")}>
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
        Each part is a percentile rank in this refresh&apos;s cohort, except sample, capacity and recency. Your copy is the sim
        at your saved settings, so it moves when they do.
      </p>
    </div>
  );
}

const POP_W = 296;

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
  /** The "top 3 parts" line under the bar (cards); off in the dense table. */
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
    const above = r.bottom + 360 > vh && r.top > 360;
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
  return (
    <div className={clsx("min-w-0", className)}>
      <button
        type="button"
        className="group flex w-full cursor-help flex-col gap-1.5 rounded-md text-left"
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
          <span className={clsx("font-num font-semibold leading-none text-foreground", big ? "text-4xl" : "text-xl")}>
            {Math.round(fit.value)}
          </span>
          <span className="font-num text-xs text-muted">/100</span>
          <span
            className={clsx(
              "ml-auto inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-medium",
              grade === "strong" ? "text-accent" : "text-muted",
            )}
          >
            {fit.caps.some((c) => c !== "fills_truncated") ? <AlertTriangle size={11} className="text-warning" aria-hidden="true" /> : null}
            {showParts ? "Copy Fit · " : ""}
            {GRADE_TEXT[grade]}
            <Info size={11} className="opacity-60 group-hover:opacity-100" aria-hidden="true" />
          </span>
        </span>
        <FitBar fit={fit} height={big ? 10 : 6} />
        {showParts ? <span className="truncate text-[11px] text-muted">
          {topParts(fit)
            .filter((p) => p.points > 0)
            .map((p) => `${p.label} +${p.points.toFixed(0)}`)
            .join(" · ") || "no part scored above zero"}
        </span> : null}
      </button>
      {pos
        ? createPortal(
            <div
              id={popId}
              role="tooltip"
              className="fixed z-50 rounded-xl border border-border bg-surface p-3 shadow-xl shadow-black/30"
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
