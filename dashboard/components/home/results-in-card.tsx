import { Fragment } from "react";
import Link from "next/link";

import { DivBar } from "@/components/home/bar";
import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { Change } from "@/components/home/change";
import { addDays, marketToday } from "@/lib/home";
import { barScale } from "@/lib/home.mjs";
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

  const rows = entries.map((entry) => ({
    entry,
    growth: resultGrowth(resultCard(entry, filings.filter((filing) => filing.symbol === entry.symbol), entry.period_end)),
  }));
  const scale = barScale(rows.flatMap(({ growth }) => [growth.revenue, growth.profit]));

  return (
    <HomeCard title="Results in" note="this week · vs year-ago quarter">
      <ul className="divide-y divide-border">
        {rows.map(({ entry, growth }) => {
          const href = `${marketPath(market.slug, "/results")}?quarter=${entry.period_end}&scope=watchlists`;
          return (
            <li key={`${entry.symbol}:${entry.period_end}`} className="py-2.5">
              <div className="flex items-center gap-3">
                <StockIdentity symbol={entry.symbol} company={entry.company} className="min-w-0 flex-1" />
                <Link href={href} className="shrink-0 rounded text-xs text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {formatDate(entry.announced_at)}
                </Link>
              </div>
              <dl className="mt-2 grid grid-cols-[3rem_minmax(0,1fr)_3.75rem] items-center gap-x-2 gap-y-1.5 text-xs">
                {(
                  [
                    ["Revenue", growth.revenue],
                    ["Profit", growth.profit],
                  ] as const
                ).map(([label, value]) => (
                  <Fragment key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd><DivBar value={value} scale={scale} /></dd>
                    <dd className="text-right"><Change value={value} unit="%" /></dd>
                  </Fragment>
                ))}
              </dl>
            </li>
          );
        })}
      </ul>
    </HomeCard>
  );
}
