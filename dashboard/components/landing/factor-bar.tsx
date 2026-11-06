"use client";

import { useLandingMarket } from "@/components/landing/landing-market";
import { SAMPLE_MARKETS, factorsFor } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

/**
 * What the ranking weighs, as one bar split into its factors for the market
 * chosen above. Guidance comes from earnings calls read for Indian companies
 * only, so on the US it is simply not there and the rest widen. The segments
 * are equal on purpose: the real weights are normalised per stock by what is
 * reported, so a drawn percentage would be a claim the page cannot keep.
 */
export function FactorBar() {
  const { market, setMarket } = useLandingMarket();
  const factors = factorsFor(market);
  return (
    <figure>
      <div role="group" aria-label="Market" className="flex w-fit gap-1 rounded-md bg-(--glass) p-0.5">
        {(Object.keys(SAMPLE_MARKETS) as (keyof typeof SAMPLE_MARKETS)[]).map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={market === key}
            onClick={() => setMarket(key)}
            className={cn("h-8 rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", market === key ? "bg-(--lens) text-foreground shadow-(--lens-shadow)" : "text-muted-foreground hover:text-foreground")}
          >
            {SAMPLE_MARKETS[key].label}
          </button>
        ))}
      </div>
      <ul className="mt-4 flex h-14 overflow-hidden rounded-md border text-xs font-medium sm:text-sm">
        {factors.map((f, i) => (
          <li
            key={f.key}
            className={cn("flex min-w-0 flex-1 items-center justify-center px-1 text-center leading-tight transition-[flex-grow] duration-500 [&:not(:first-child)]:border-l", i % 2 ? "bg-(--control)" : "bg-card", f.key === "guidance" && "bg-brand-soft text-brand")}
          >
            {f.label}
          </li>
        ))}
      </ul>
      <figcaption className="mt-3 text-xs text-muted-foreground">
        {market === "ind" ? "Six things, India: management guidance is read from earnings calls." : "Five things, US: there are no earnings-call readings, so the rest carry the ranking."} Segment widths are schematic, not exact weights.
      </figcaption>
    </figure>
  );
}
