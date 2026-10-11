import { heatLevel, WEEKDAYS } from "@/lib/scout/file/strategy";
import type { StrategyFingerprint } from "@/lib/scout/types";
import { axisBars, realGrid } from "./StrategyHeatmapGrid";

const CELL = 14;
const GAP = 2;
const LEFT = 30;
const TOP = 14;
const BAR = 22;
const hh = (h: number) => String(h).padStart(2, "0");

type Fp = Pick<StrategyFingerprint, "hour_hist_utc" | "weekday_hist"> & { entries_by_dow_hour?: number[][] | null };

/**
 * When they enter. With the api's real 7 x 24 matrix (entries_by_dow_hour):
 * a heatmap of real counts with exact marginal bars. Without it (a fingerprint
 * cached before the field): two plain bar charts, never cells made up from the
 * two totals (UX audit #9).
 */
export function StrategyHeatmap({ fp }: { fp: Fp }) {
  const g = realGrid(fp.entries_by_dow_hour);
  if (!g) return <AxisBars fp={fp} />;
  if (g.total === 0) return <p className="text-sm text-muted">No entries to place on the clock yet.</p>;

  const gridW = 24 * (CELL + GAP);
  const gridH = 7 * (CELL + GAP);
  const w = LEFT + gridW + 6 + BAR;
  const h = TOP + gridH + 6 + BAR + 12;
  const hMax = Math.max(1, ...g.hours);
  const dMax = Math.max(1, ...g.weekdays);
  const peak = `Busiest hour ${g.peakHour === null ? "n/a" : `${hh(g.peakHour)}:00`} UTC, busiest day ${g.peakWeekday === null ? "n/a" : WEEKDAYS[g.peakWeekday]}.`;

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <svg width={w} height={h} role="img" aria-label={`Entry times. ${peak}`}>
          {[0, 6, 12, 18].map((hr) => (
            <text key={hr} x={LEFT + hr * (CELL + GAP)} y={10} fontSize="9" fill="var(--muted)">
              {hh(hr)}
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
                fill={v > 0 ? `color-mix(in srgb, var(--accent) ${Math.round(15 + heatLevel(v, g.max) * 85)}%, var(--surface-2))` : "var(--surface-2)"}
              >
                <title>{`${WEEKDAYS[d]} ${hh(hr)}:00 UTC: ${v} ${v === 1 ? "entry" : "entries"}`}</title>
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
              <title>{`${hh(hr)}:00 UTC: ${v} entries`}</title>
            </rect>
          ))}
        </svg>
      </div>
      <p className="text-[11px] text-muted">Times in UTC. Each cell is the number of trips opened in that hour on that weekday; bars are the totals.</p>
    </div>
  );
}

/** Fallback for fingerprints without the matrix: the two exact histograms, side by side. */
function AxisBars({ fp }: { fp: Fp }) {
  const b = axisBars(fp.hour_hist_utc, fp.weekday_hist);
  if (b.total === 0) return <p className="text-sm text-muted">No entries to place on the clock yet.</p>;
  const hMax = Math.max(1, ...b.hours);
  const dMax = Math.max(1, ...b.weekdays);
  const H = 60;
  const hw = 24 * (CELL + GAP);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-6 overflow-x-auto">
        <svg width={hw} height={H + 14} role="img" aria-label="Entries per UTC hour">
          {b.hours.map((v, hr) => (
            <rect key={hr} x={hr * (CELL + GAP)} y={H - (v / hMax) * H} width={CELL} height={(v / hMax) * H} rx="1" fill="var(--accent)">
              <title>{`${hh(hr)}:00 UTC: ${v} entries`}</title>
            </rect>
          ))}
          {[0, 6, 12, 18].map((hr) => (
            <text key={hr} x={hr * (CELL + GAP)} y={H + 11} fontSize="9" fill="var(--muted)">
              {hh(hr)}
            </text>
          ))}
        </svg>
        <svg width={7 * 26} height={H + 14} role="img" aria-label="Entries per weekday">
          {b.weekdays.map((v, d) => (
            <rect key={d} x={d * 26} y={H - (v / dMax) * H} width={20} height={(v / dMax) * H} rx="1" fill="var(--accent)">
              <title>{`${WEEKDAYS[d]}: ${v} entries`}</title>
            </rect>
          ))}
          {WEEKDAYS.map((d, i) => (
            <text key={d} x={i * 26} y={H + 11} fontSize="9" fill="var(--muted)">
              {d}
            </text>
          ))}
        </svg>
      </div>
      <p className="text-[11px] text-muted">Times in UTC. Entries per hour and per weekday. The per-hour-per-day grid appears once this fingerprint is rebuilt.</p>
    </div>
  );
}
