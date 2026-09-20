"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { MARKET_LIST, switchMarketPath, type Market } from "@/lib/markets";

/**
 * Which market the screener is showing.
 *
 * A segmented control beside the brand rather than another entry in the
 * primary nav. Market and destination are independent axes -- every
 * destination exists in every market -- so putting them in one row would
 * misrepresent the structure and would multiply the nav's length by the market
 * count. Sitting next to the brand also reads correctly: it qualifies *what
 * you are looking at*, the way the run date beneath it does, rather than
 * offering somewhere else to go.
 *
 * Rendered as real links, not buttons with an onClick. Each market's view has
 * its own URL, so a middle click or a bookmark works, and the switch costs a
 * normal navigation rather than a client-side refetch.
 *
 * The track and filled active pill deliberately match NavLink, because both
 * are "one of these is current" controls and inventing a second visual
 * language for the same idea would make the header read as two unrelated
 * widgets.
 */
export function MarketSwitch({ current }: { current: Market }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Market"
      className="flex shrink-0 gap-1 rounded-full border bg-muted p-1"
    >
      {MARKET_LIST.map((market) => {
        const active = market.slug === current.slug;
        return (
          <Link
            key={market.slug}
            href={switchMarketPath(pathname, market.slug)}
            aria-current={active ? "true" : undefined}
            title={market.name}
            className={cn(
              // inline-flex + items-center, not just min-height. A bare
              // min-height reserves the box but leaves the text sitting at the
              // top of it, which is what made these read as misaligned against
              // the nav pills beside them -- those centre via NavLink's own
              // flex. justify-center keeps NSE and US optically even despite
              // their different widths.
              "inline-flex min-h-8 items-center justify-center rounded-full",
              "px-3.5 text-xs font-semibold leading-none",
              "transition-[background-color,color] duration-(--duration-base) ease-(--ease-standard)",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              active
                ? "bg-primary text-primary-foreground shadow-xs"
                : "text-muted-foreground hover:bg-background hover:text-foreground",
            )}
          >
            {market.label}
            <span className="sr-only"> screener</span>
          </Link>
        );
      })}
    </nav>
  );
}
