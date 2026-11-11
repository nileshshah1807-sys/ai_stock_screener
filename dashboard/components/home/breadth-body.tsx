"use client";

import Link from "next/link";

import { Sparkline } from "@/components/home/sparkline";
import { Gauge } from "@/components/home/gauge";
import { TickFlash } from "@/components/tick-flash";
import { useMarket } from "@/components/market-provider";
import type { BreadthNow } from "@/lib/home-market";
import { marketPath } from "@/lib/markets";
import { LIVE_DENOMINATORS, useLiveBreadth } from "@/lib/use-live-breadth";

const MEASURES = [
  { key: "e50", label: "Above 50-day average", short: "above 50-day" },
  { key: "e200", label: "Above 200-day average", short: "above 200-day" },
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
      <ul className="grid grid-cols-2 gap-3">
        {MEASURES.map(({ key, label, short }) => {
          const total = live?.counts?.[LIVE_DENOMINATORS[key]];
          const count = live?.counts?.[key];
          const percent = total && count !== undefined ? (count / total) * 100 : now[key];
          return (
            <li key={key}>
              <div
                role="img"
                aria-label={percent === null ? `${label}: not measured` : `${percent.toFixed(0)}% ${label.toLowerCase()}`}
                className="relative"
              >
                <Gauge percent={percent} />
                <TickFlash tick={live?.ticks[key]} className="tabular absolute inset-x-0 bottom-3 text-center font-mono text-xl font-semibold">
                  {percent === null ? "—" : `${percent.toFixed(0)}%`}
                </TickFlash>
              </div>
              <span className="mt-1 block text-center text-xs text-muted-foreground">{short}</span>
            </li>
          );
        })}
      </ul>
      {now.trend50.length > 1 ? (
        <div className="mt-auto pt-4">
          <p className="mb-1 flex justify-between text-[11px] text-muted-foreground">
            <span>Above 50-day, last month</span>
            <span className="tabular font-mono">{now.trend50.at(-1)!.toFixed(0)}%</span>
          </p>
          <Sparkline values={now.trend50} />
        </div>
      ) : null}
      <Link prefetch={false}
        href={marketPath(market.slug, "/market")}
        className="mt-4 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Breadth charts
      </Link>
    </>
  );
}
