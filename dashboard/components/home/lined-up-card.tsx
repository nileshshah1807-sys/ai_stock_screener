import Link from "next/link";

import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate, formatInteger } from "@/lib/format";
import { marketToday } from "@/lib/home";
import { getLinedUp } from "@/lib/home-market";
import { marketPath, type Market } from "@/lib/markets";

/**
 * Results due in the next seven days: the count, the next five companies to
 * report with their dates, and a way into the Results page's full list.
 */
export async function LinedUpCard({ market }: { market: Market }) {
  const lined = await getLinedUp(market.code, marketToday(market));
  if (!lined) return null;

  return (
    <HomeCard title="Lined up this week" note="results due">
      <p className="tabular mb-2 text-2xl font-semibold tracking-tight">{formatInteger(lined.count)}</p>
      <ul className="divide-y divide-border">
        {lined.next.map((row) => (
          <li key={row.symbol} className="flex items-center gap-3 py-2">
            <StockIdentity symbol={row.symbol} className="min-w-0 flex-1" />
            <span className="tabular shrink-0 text-xs text-muted-foreground">{formatDate(row.event_date)}</span>
          </li>
        ))}
      </ul>
      {lined.count > lined.next.length ? (
        <Link
          href={marketPath(market.slug, "/results")}
          className="mt-2 self-start rounded text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          All {formatInteger(lined.count)} on the Results page
        </Link>
      ) : null}
    </HomeCard>
  );
}
