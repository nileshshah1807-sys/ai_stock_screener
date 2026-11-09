"use client";

import Link from "next/link";

import { TickFlash } from "@/components/tick-flash";
import { useMarket } from "@/components/market-provider";
import type { BreadthNow } from "@/lib/home-market";
import { marketPath } from "@/lib/markets";
import { LIVE_DENOMINATORS, useLiveBreadth } from "@/lib/use-live-breadth";

const MEASURES = [
  { key: "e50", label: "Above 50-day average" },
  { key: "e200", label: "Above 200-day average" },
] as const;

/**
 * Share of the market above its 50- and 200-day averages: the last published
 * close, replaced by the live count (`live_breadth`) once quotes land.
 */
export function BreadthBody({ now }: { now: BreadthNow }) {
  const market = useMarket();
  const live = useLiveBreadth(market.code, { scope: "market", name: "" });

  return (
    <>
      <ul className="space-y-4">
        {MEASURES.map(({ key, label }) => {
          const total = live?.counts?.[LIVE_DENOMINATORS[key]];
          const count = live?.counts?.[key];
          const percent = total && count !== undefined ? (count / total) * 100 : now[key];
          return (
            <li key={key}>
              <div className="flex items-baseline justify-between text-sm">
                <span>{label}</span>
                <TickFlash tick={live?.ticks[key]} className="tabular font-mono font-semibold">
                  {percent === null ? "—" : `${percent.toFixed(0)}%`}
                </TickFlash>
              </div>
              <div
                className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label={percent === null ? `${label}: not measured` : `${percent.toFixed(0)}% ${label.toLowerCase()}`}
              >
                <span className="block h-full bg-foreground/60" style={{ width: `${percent ?? 0}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      <Link
        href={marketPath(market.slug, "/market")}
        className="mt-4 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Breadth charts
      </Link>
    </>
  );
}
