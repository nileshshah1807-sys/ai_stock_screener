import Link from "next/link";

import { HomeCard } from "@/components/home/home-card";
import { QuickWatch } from "@/components/home/quick-watch";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate, formatInteger, formatPercent } from "@/lib/format";
import { marketToday } from "@/lib/home";
import { getResultsSeason, type SeasonMover } from "@/lib/home-market";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

function Movers({ title, rows }: { title: string; rows: SeasonMover[] }) {
  if (!rows.length) return null;
  return (
    <div>
      <h3 className="pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <li key={row.symbol} className="flex items-center gap-3 py-2">
            <StockIdentity symbol={row.symbol} company={row.company} className="min-w-0 flex-1" />
            <span className={cn("tabular shrink-0 font-mono text-xs", row.change >= 0 ? "text-positive" : "text-negative")}>
              {formatPercent(row.change, 0, true)}
            </span>
            <QuickWatch symbol={row.symbol} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * How many companies reported on the latest results day (today, once any has)
 * and the largest year-on-year net profit rises and falls among them, from the
 * same stored filings as the Results page.
 */
export async function ResultsSeasonCard({ market }: { market: Market }) {
  const today = marketToday(market);
  const season = await getResultsSeason(market.code, today, market.timezone);
  if (!season) return null;

  return (
    <HomeCard title="Results season" note={season.day === today ? "today" : formatDate(season.day)}>
      <p className="mb-3 text-sm">
        <span className="tabular text-2xl font-semibold tracking-tight">{formatInteger(season.count)}</span>{" "}
        <span className="text-muted-foreground">{season.count === 1 ? "company" : "companies"} reported</span>
      </p>
      <div className="space-y-3">
        <Movers title="Biggest profit rises" rows={season.rises} />
        <Movers title="Biggest profit falls" rows={season.falls} />
      </div>
      <Link
        href={marketPath(market.slug, "/results")}
        className="mt-3 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        All results
      </Link>
    </HomeCard>
  );
}
