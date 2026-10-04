import { heatLevel, hourWeekdayGrid, WEEKDAYS } from "@/lib/scout/file/strategy";
import type { StrategyFingerprint } from "@/lib/scout/types";

const CELL = 14;
const GAP = 2;
const LEFT = 30;
const TOP = 14;
const BAR = 22;

/** Hour-of-day (UTC) x weekday entry heatmap, with exact marginal bars on the right and bottom. */
export function StrategyHeatmap({ fp }: { fp: Pick<StrategyFingerprint, "hour_hist_utc" | "weekday_hist"> }) {
  const g = hourWeekdayGrid(fp);
  const gridW = 24 * (CELL + GAP);
  const gridH = 7 * (CELL + GAP);
  const w = LEFT + gridW + 6 + BAR;
  const h = TOP + gridH + 6 + BAR + 12;
  const hMax = Math.max(1, ...g.hours);
  const dMax = Math.max(1, ...g.weekdays);

  if (g.total === 0) return <p className="text-sm text-muted">No entries to place on the clock yet.</p>;

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <svg width={w} height={h} role="img" aria-label={`Entry times. Busiest hour ${g.peakHour}:00 UTC, busiest day ${g.peakWeekday === null ? "n/a" : WEEKDAYS[g.peakWeekday]}.`}>
          {[0, 6, 12, 18].map((hr) => (
            <text key={hr} x={LEFT + hr * (CELL + GAP)} y={10} fontSize="9" fill="var(--muted)">
              {String(hr).padStart(2, "0")}
            </text>
          ))}
          {WEEKDAYS.map((d, i) => (
            <text key={d} x={0} y={TOP + i * (CELL + GAP) + CELL - 3} fontSize="9" fill="var(--muted)">
              {d}
            </text>
          ))}
          {g.cells.map((row, d) =>
            row.map((v, hr) => (
              <rect
                key={`${d}-${hr}`}
                x={LEFT + hr * (CELL + GAP)}
                y={TOP + d * (CELL + GAP)}
                width={CELL}
                height={CELL}
                rx="2"
                fill={`color-mix(in srgb, var(--accent) ${Math.round(8 + heatLevel(v, g.max) * 92)}%, var(--surface-2))`}
              >
                <title>{`${WEEKDAYS[d]} ${String(hr).padStart(2, "0")}:00 UTC: about ${v.toFixed(1)} entries`}</title>
              </rect>
            )),
          )}
          {g.weekdays.map((v, d) => (
            <rect key={`d${d}`} x={LEFT + gridW + 6} y={TOP + d * (CELL + GAP) + 2} width={(v / dMax) * BAR} height={CELL - 4} rx="1" fill="var(--muted)">
              <title>{`${WEEKDAYS[d]}: ${v} entries`}</title>
            </rect>
          ))}
          {g.hours.map((v, hr) => (
            <rect key={`h${hr}`} x={LEFT + hr * (CELL + GAP) + 2} y={TOP + gridH + 6} width={CELL - 4} height={(v / hMax) * BAR} rx="1" fill="var(--muted)">
              <title>{`${String(hr).padStart(2, "0")}:00 UTC: ${v} entries`}</title>
            </rect>
          ))}
        </svg>
      </div>
      <p className="text-[11px] text-muted">
        Times in UTC. Bars are exact entry counts per hour and per weekday; cells combine the two (the api sends totals per axis, not per
        cell).
      </p>
    </div>
  );
}
