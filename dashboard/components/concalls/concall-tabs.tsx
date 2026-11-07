import Link from "next/link";

import { GlassTrack } from "@/components/glass-track";
import { cn } from "@/lib/utils";

export type ConcallView = "live" | "latest" | "upcoming";

const VIEWS: { view: ConcallView; label: string }[] = [
  { view: "live", label: "Live now" },
  { view: "latest", label: "Latest" },
  { view: "upcoming", label: "Upcoming" },
];

/** The Concalls page's three views, as links: each has its own URL (`?view=`). */
export function ConcallTabs({ base, active, liveCount }: { base: string; active: ConcallView; liveCount: number }) {
  return (
    <GlassTrack label="Concall views" className="w-max gap-0.5 p-0.5">
      {VIEWS.map(({ view, label }) => (
        <Link
          key={view}
          href={view === "latest" ? base : `${base}?view=${view}`}
          aria-current={view === active ? "page" : undefined}
          className={cn(
            "inline-flex min-h-7 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium leading-none",
            "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
            "active:scale-[0.92] active:duration-(--duration-press) active:ease-out",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            view === active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {view === "live" && liveCount ? <span aria-hidden className="size-1.5 rounded-full bg-negative" /> : null}
          {label}
          {view === "live" && liveCount ? <span className="sr-only">, {liveCount} on air</span> : null}
        </Link>
      ))}
    </GlassTrack>
  );
}
