import Link from "next/link";

import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { Change } from "@/components/home/change";
import { addDays, marketToday } from "@/lib/home";
import { getRecentResults, getResultFilings } from "@/lib/home-watch";
import { resultGrowth } from "@/lib/home-watch.mjs";
import { formatDate } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";
import { resultCard } from "@/lib/results.mjs";

/**
 * Watched stocks that filed in the last week, with revenue and profit growth
 * against the year-ago quarter, each linking to its Results card. Growth is
 * the Results page's own (`resultCard`), so a figure here is that card's.
 */
export async function ResultsInCard({ market }: { market: Market }) {
  const since = addDays(marketToday(market), -7);
  const entries = await getRecentResults(market.code, await getWatchedSymbols(market.code), since);
  if (!entries.length) return null;
  const filings = await getResultFilings(market.code, entries);

  return (
    <HomeCard title="Results in" note="this week">
      <ul className="divide-y divide-border">
        {entries.map((entry) => {
          const growth = resultGrowth(
            resultCard(entry, filings.filter((filing) => filing.symbol === entry.symbol), entry.period_end),
          );
          const href = `${marketPath(market.slug, "/results")}?quarter=${entry.period_end}&scope=watchlists`;
          return (
            <li key={`${entry.symbol}:${entry.period_end}`} className="flex items-center gap-3 py-2">
              <StockIdentity symbol={entry.symbol} company={entry.company} className="min-w-0 flex-1" />
              <Link href={href} className="tabular shrink-0 text-right text-xs hover:underline">
                <span className="block text-muted-foreground">{formatDate(entry.announced_at)} · YoY</span>
                <span className="text-muted-foreground">Rev </span>
                <Change value={growth.revenue} unit="%" />
                <span className="text-muted-foreground"> · Profit </span>
                <Change value={growth.profit} unit="%" />
              </Link>
            </li>
          );
        })}
      </ul>
    </HomeCard>
  );
}
