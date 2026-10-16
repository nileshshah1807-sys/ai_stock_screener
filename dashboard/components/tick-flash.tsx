"use client";

import { useState, type ReactNode } from "react";

import type { Tick } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

/*
 * A live price whose background turns green when it rose and red when it fell
 * since the last read, then fades back (TICK_FLASH_MS in lib/live-quotes.mjs).
 *
 * The text keeps its own colour; only the ground behind it changes. A move
 * the tab saw before this element mounted -- a sort, a page change, a step
 * back to the grid -- is old news and does not flash again.
 */
export function TickFlash({
  tick,
  className,
  children,
}: {
  tick: Tick | null | undefined;
  className?: string;
  children: ReactNode;
}) {
  const [mountedAt] = useState(() => Date.now());
  const fresh = tick && tick.at >= mountedAt ? tick : null;
  return (
    <span
      // A new key per move restarts the animation.
      key={fresh?.at ?? "still"}
      className={cn(
        "-mx-1 rounded-[4px] px-1",
        fresh?.direction === "up" && "animate-tick-up",
        fresh?.direction === "down" && "animate-tick-down",
        className,
      )}
    >
      {children}
    </span>
  );
}
