import { intradayGeometry, type Point } from "@/lib/intraday.mjs";
import { cn } from "@/lib/utils";

/**
 * Today's line of an index, in the Sparkline's box: drawn across the whole
 * session from the open, over a dashed line at the previous close, green above
 * it and red below. While the market is open the last point beats, as on the
 * Market page's charts.
 */
export function IntradayLine({
  points,
  base,
  sessionOpen,
  sessionClose,
  live,
  width = 120,
  height = 36,
}: {
  points: Point[];
  base: number | null;
  sessionOpen: string;
  sessionClose: string;
  live: boolean;
  width?: number;
  height?: number;
}) {
  const geometry = intradayGeometry(points, { base, sessionOpen, sessionClose, width, height });
  if (!geometry) return null;
  const { line, last, baseY, rising } = geometry;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
      className={cn("block h-auto w-full overflow-visible", rising ? "text-positive" : "text-negative")}
    >
      {baseY === null ? null : (
        <line x1={0} x2={width} y1={baseY} y2={baseY} strokeWidth={1} strokeDasharray="2 3" className="stroke-muted-foreground/50" />
      )}
      <polygon points={`0,${height} ${line} ${last[0]},${height}`} className="fill-current opacity-10" />
      <polyline points={line} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" className="stroke-current" />
      <circle cx={last[0]} cy={last[1]} r={2} className="fill-current" />
      {live ? (
        <circle cx={last[0]} cy={last[1]} r={2} className="origin-center animate-heartbeat fill-current [transform-box:fill-box]" />
      ) : null}
    </svg>
  );
}
