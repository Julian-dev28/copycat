"use client";

import { useState } from "react";
import { formatSignedUsd } from "@/lib/format";
import { buildCalendar, type CalendarCell } from "@/lib/scout/calendar";
import type { CurvePoint } from "@/lib/scout/types";
import { formatSignedUsdCompact } from "@/lib/scout/window";

const CELL = 12;
const GAP = 2;
const DAYS = ["Mon", "", "Wed", "", "Fri", "", ""];

/** Diverging fill: green for gains, red for losses, 4 steps each; flat days neutral, no-data days hollow. */
function fill(c: CalendarCell): string {
  if (c.value === null) return "transparent";
  if (c.level === 0) return "var(--surface-2)";
  const pct = [0, 28, 48, 70, 100][Math.abs(c.level)];
  const base = c.level > 0 ? "var(--success)" : "var(--danger)";
  return `color-mix(in srgb, ${base} ${pct}%, var(--surface-2))`;
}

function dayLabel(t: number): string {
  return new Date(t).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function PnlCalendar({ daily }: { daily: CurvePoint[] }) {
  const [days, setDays] = useState(182);
  const [hover, setHover] = useState<CalendarCell | null>(null);
  const grid = buildCalendar(daily, days);
  const w = grid.weeks.length * (CELL + GAP) + 28;
  const h = 7 * (CELL + GAP) + 16;
  const shown = hover ?? grid.best;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
          <span>
            Net <span className={`font-num font-semibold ${grid.total >= 0 ? "text-success" : "text-danger"}`}>{formatSignedUsdCompact(grid.total)}</span>
          </span>
          <span>
            <span className="font-num text-foreground">{grid.green}</span> green days · <span className="font-num text-foreground">{grid.red}</span> red
          </span>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Calendar range">
          {[
            [91, "3m"],
            [182, "6m"],
            [365, "1y"],
          ].map(([d, l]) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={days === d}
              onClick={() => setDays(d as number)}
              className={`rounded-md px-2 py-0.5 ${days === d ? "bg-accent text-accent-foreground" : "text-muted hover:text-foreground"}`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg width={w} height={h} role="img" aria-label={`Daily PnL calendar, ${grid.green} green and ${grid.red} red days, net ${formatSignedUsd(Math.round(grid.total))}`}>
          {grid.months.map((m) => (
            <text key={`${m.col}-${m.label}`} x={28 + m.col * (CELL + GAP)} y={9} fontSize="9" fill="var(--muted)">
              {m.label}
            </text>
          ))}
          {DAYS.map((d, i) =>
            d ? (
              <text key={d} x={0} y={16 + i * (CELL + GAP) + CELL - 3} fontSize="9" fill="var(--muted)">
                {d}
              </text>
            ) : null,
          )}
          {grid.weeks.map((week, col) =>
            week.map((c, row) => (
              <rect
                key={c.t_ms}
                x={28 + col * (CELL + GAP)}
                y={14 + row * (CELL + GAP)}
                width={CELL}
                height={CELL}
                rx="2"
                fill={fill(c)}
                stroke={hover?.t_ms === c.t_ms ? "var(--foreground)" : c.value === null ? "var(--border)" : "none"}
                strokeWidth={hover?.t_ms === c.t_ms ? 1.5 : 1}
                onPointerEnter={() => setHover(c)}
                onPointerLeave={() => setHover(null)}
              >
                <title>{`${dayLabel(c.t_ms)}: ${c.value === null ? "no data" : formatSignedUsd(Math.round(c.value))}`}</title>
              </rect>
            )),
          )}
        </svg>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted" aria-live="polite">
        <span>
          {shown ? (
            <>
              {hover ? "" : "Best day: "}
              {dayLabel(shown.t_ms)}{" "}
              <span className={`font-num font-semibold ${(shown.value ?? 0) >= 0 ? "text-success" : "text-danger"}`}>
                {shown.value === null ? "no data" : formatSignedUsd(Math.round(shown.value))}
              </span>
            </>
          ) : (
            "No daily PnL yet."
          )}
        </span>
        <span className="inline-flex items-center gap-1">
          Loss
          {[-4, -2, 0, 2, 4].map((l) => (
            <span key={l} className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ background: fill({ t_ms: 0, value: l, level: l }) }} />
          ))}
          Gain
        </span>
      </div>
    </div>
  );
}
