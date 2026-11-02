import { formatInteger } from "@/lib/format";

/**
 * One line's median growth by quarter, as bars in SVG. Server-rendered: the
 * viewBox scales it to its panel, so there is nothing to measure.
 *
 * Every bar carries its figure and the companies it rests on sit under its
 * quarter. A quarter with no rate is a dash on the baseline, not a zero. The
 * newest quarter is dashed and unfilled while its season is still arriving:
 * its median rests on the early filers. One neutral colour; a fall is the
 * negative colour, and the figure is unsigned on the bar, as direction is
 * the bar's, with the signed value in the table beneath.
 */

export type AnalysisPoint = { label: string; median: number | null; n: number };

const W = 320;
const H = 170;
const PAD = { top: 20, right: 4, bottom: 36, left: 4 };

export function AnalysisChart({
  title,
  points,
  inProgress,
}: {
  title: string;
  points: AnalysisPoint[];
  /** The newest point is a season still arriving. */
  inProgress: boolean;
}) {
  const known = points.map((point) => point.median).filter((value): value is number => value !== null);
  const max = Math.max(5, ...known);
  const lowest = Math.min(0, ...known);
  // Room under the baseline for a fall's label, so it never meets the quarter's.
  const min = lowest < 0 ? lowest - (max - lowest) * 0.18 : 0;
  const y = (value: number) => PAD.top + ((max - value) / (max - min)) * (H - PAD.top - PAD.bottom);
  const group = (W - PAD.left - PAD.right) / points.length;
  const bar = Math.min(28, group * 0.55);
  const zero = y(0);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}, median year-on-year growth by quarter`} className="block h-auto w-full overflow-visible">
      <line x1={0} x2={W} y1={zero} y2={zero} stroke="var(--border)" />
      {points.map((point, index) => {
        const center = PAD.left + group * (index + 0.5);
        const live = inProgress && index === points.length - 1;
        const value = point.median;
        const color = value !== null && value < 0 ? "var(--negative)" : "var(--muted-foreground)";
        return (
          <g key={point.label}>
            {value === null ? (
              <text x={center} y={zero - 6} textAnchor="middle" className="fill-muted-foreground text-[10.5px]">
                <title>No company had a growth rate</title>
                –
              </text>
            ) : (
              <>
                <title>{`Median ${value.toFixed(1)}% across ${formatInteger(point.n)} companies`}</title>
                <rect
                  x={center - bar / 2}
                  y={y(Math.max(value, 0))}
                  width={bar}
                  height={Math.max(1, Math.abs(y(value) - zero))}
                  rx={2}
                  fill={live ? "none" : color}
                  stroke={color}
                  strokeWidth={live ? 1.5 : 0}
                  strokeDasharray={live ? "3 2" : undefined}
                />
                <text
                  x={center}
                  y={value >= 0 ? y(value) - 5 : y(value) + 12}
                  textAnchor="middle"
                  className="tabular fill-foreground text-[11px] font-semibold"
                >
                  {Math.abs(value).toFixed(1)}%
                </text>
              </>
            )}
            <text x={center} y={H - 20} textAnchor="middle" className="fill-foreground text-[10.5px]">
              {point.label}
            </text>
            <text x={center} y={H - 7} textAnchor="middle" className="tabular fill-muted-foreground text-[10.5px]">
              {point.n ? formatInteger(point.n) : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
