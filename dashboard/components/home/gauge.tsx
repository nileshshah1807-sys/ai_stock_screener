import { cn } from "@/lib/utils";

const RADIUS = 40;

/**
 * Half-circle gauge for a share, 0-100. The arc draws in from the left; the
 * figure is printed in the middle by the caller (it may be live), so the arc
 * itself is decorative.
 */
export function Gauge({ percent, className }: { percent: number | null; className?: string }) {
  const arc = `M ${50 - RADIUS} 50 A ${RADIUS} ${RADIUS} 0 0 1 ${50 + RADIUS} 50`;
  return (
    <svg viewBox="0 0 100 56" aria-hidden className={cn("block w-full", className)}>
      <path d={arc} pathLength={1} fill="none" strokeWidth={7} strokeLinecap="round" className="stroke-muted" />
      {percent === null ? null : (
        <path
          d={arc}
          pathLength={1}
          fill="none"
          strokeWidth={7}
          strokeLinecap="round"
          // Past half the market is above its average: the arc reads as healthy.
          className={cn("animate-draw", percent >= 50 ? "stroke-positive" : "stroke-negative")}
          strokeDasharray={`${Math.max(0.001, Math.min(1, percent / 100))} 1`}
        />
      )}
    </svg>
  );
}
