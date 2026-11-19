import Link from "next/link";

import { GlassTrack } from "@/components/glass-track";
import { BOARDS, listQuery } from "@/lib/ipos.mjs";
import { cn } from "@/lib/utils";

/**
 * Mainboard, SME or both. Links, as MarketSwitch is: each board's list has its
 * own URL, so a bookmark or a shared link opens on the same board.
 */
export function BoardFilter({
  base,
  current,
  counts,
  showAll,
}: {
  base: string;
  current: string;
  counts: Record<string, number>;
  showAll: boolean;
}) {
  return (
    <GlassTrack label="Board" className="w-max gap-0.5 p-0.5">
      {BOARDS.map(({ value, label }) => {
        const active = value === current;
        return (
          <Link
            prefetch={false}
            key={value}
            href={`${base}${listQuery(value, showAll)}`}
            aria-current={active ? "true" : undefined}
            className={cn(
              "touch-target inline-flex min-h-7 items-center gap-1.5 rounded-md px-3 text-[0.8125rem] font-medium",
              "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
              "active:scale-[0.95] active:duration-(--duration-press) active:ease-out",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
            <span className="tabular font-mono text-[11px] font-normal text-muted-foreground">{counts[value] ?? 0}</span>
          </Link>
        );
      })}
    </GlassTrack>
  );
}
