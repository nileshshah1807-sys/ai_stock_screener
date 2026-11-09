import { trendPoints } from "@/lib/home-watch.mjs";
import { cn } from "@/lib/utils";

const PAD = 2;

/**
 * A line with a soft fill under it that draws itself in once. Plain SVG: no
 * chart library in the page's bundle. The colour follows the direction of the
 * line, and the box it is given sets the size.
 */
export function Sparkline({ values, width = 120, height = 36, className }: { values: number[]; width?: number; height?: number; className?: string }) {
  const line = trendPoints(values, width, height - PAD * 2);
  if (!line) return null;
  const shifted = line
    .split(" ")
    .map((pair: string) => {
      const [x, y] = pair.split(",");
      return `${x},${(Number(y) + PAD).toFixed(1)}`;
    })
    .join(" ");
  const rising = values.at(-1)! >= values[0];
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
      className={cn("block h-auto w-full", rising ? "text-positive" : "text-negative", className)}
    >
      <polygon points={`0,${height} ${shifted} ${width},${height}`} className="fill-current opacity-10" />
      <polyline
        points={shifted}
        pathLength={1}
        fill="none"
        strokeWidth={1.75}
        strokeLinejoin="round"
        strokeLinecap="round"
        strokeDasharray={1}
        className="animate-draw stroke-current"
      />
    </svg>
  );
}
