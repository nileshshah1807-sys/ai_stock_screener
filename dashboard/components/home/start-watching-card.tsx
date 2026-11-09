import Link from "next/link";

import { HomeCard } from "@/components/home/home-card";
import { QuickWatch } from "@/components/home/quick-watch";
import { StockIdentity } from "@/components/stock-identity";
import { formatPercent } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { getLiveMarket } from "@/lib/queries";
import { cn } from "@/lib/utils";

const SHOWN = 5;

/**
 * The empty state for a viewer who watches nothing: today's biggest gainers
 * on the market's headline index, each with a one-tap add, so the lists that
 * make Home personal start from somewhere. Falls back to a plain invitation
 * when there are no live movers to offer.
 */
export async function StartWatchingCard({ market }: { market: Market }) {
  const { live } = await getLiveMarket(market.code);
  const movers = live?.indices[0]?.gainers.slice(0, SHOWN) ?? [];

  return (
    <HomeCard title="Make this page yours" className="lg:col-span-2">
      <p className="mb-3 max-w-prose text-sm text-muted-foreground">
        Watch a few stocks and Home leads with what changed on them: new results, calls, filings and
        trades. Start with today&apos;s movers, or{" "}
        <Link href={marketPath(market.slug, "/screener")} className="underline underline-offset-2 hover:no-underline">
          pick from the screener
        </Link>
        .
      </p>
      {movers.length ? (
        <ul className="divide-y divide-border">
          {movers.map((mover) => (
            <li key={mover.symbol} className="flex items-center gap-3 py-2">
              <StockIdentity symbol={mover.symbol} company={mover.company} className="min-w-0 flex-1" />
              <span className={cn("tabular shrink-0 text-sm font-medium", mover.change_pct >= 0 ? "text-positive" : "text-negative")}>
                {formatPercent(mover.change_pct)}
              </span>
              <QuickWatch symbol={mover.symbol} />
            </li>
          ))}
        </ul>
      ) : null}
    </HomeCard>
  );
}
