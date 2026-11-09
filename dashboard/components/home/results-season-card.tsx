import Link from "next/link";

import { Bar } from "@/components/home/bar";
import { CountUp } from "@/components/motion";
import { HomeCard } from "@/components/home/home-card";
import { QuickWatch } from "@/components/home/quick-watch";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate, formatInteger, formatPercent } from "@/lib/format";
import { marketToday } from "@/lib/home";
import { barScale } from "@/lib/home.mjs";
import { getResultsSeason, type SeasonMover } from "@/lib/home-market";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

const BAR_CAP = 300;
/** Fewer movers than this is a line, not a card. */
const MIN_ROWS = 3;

function Movers({ title, rows, scale }: { title: string; rows: SeasonMover[]; scale: number }) {
  if (!rows.length) return null;
  return (
    <div>
      <h3 className="pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <li key={row.symbol} className="py-2">
            <div className="flex items-center gap-3">
              <StockIdentity symbol={row.symbol} company={row.company} className="min-w-0 flex-1" />
              <span className={cn("tabular shrink-0 font-mono text-xs", row.change >= 0 ? "text-positive" : "text-negative")}>
                {row.loss ? "turned to loss" : formatPercent(row.change, 0, true)}
              </span>
              <QuickWatch symbol={row.symbol} />
            </div>
            <Bar value={row.loss ? scale : row.change} scale={scale} tone={row.change >= 0 ? "positive" : "negative"} className="mt-1.5 h-1" />
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
  // One outlier rate (a tiny base) must not flatten the rest: bars cap at 300%,
  // and a company that fell into loss has no rate, so its bar is full.
  const scale = Math.min(BAR_CAP, barScale([...season.rises, ...season.falls].filter((row) => !row.loss).map((row) => row.change)));
  const shown = season.rises.length + season.falls.length;
  if (shown < MIN_ROWS) {
    return (
      <section aria-label="Results season" className="panel flex animate-rise flex-wrap items-baseline gap-x-3 gap-y-1 p-4 sm:px-5">
        <h2 className="text-sm font-semibold tracking-[-0.01em]">Results season</h2>
        <p className="text-sm text-muted-foreground">
          {formatInteger(season.count)} {season.count === 1 ? "company" : "companies"} reported {season.day === today ? "today" : formatDate(season.day)}
        </p>
        <Link href={marketPath(market.slug, "/results")} className="ml-auto rounded text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          All results
        </Link>
      </section>
    );
  }

  return (
    <HomeCard title="Results season" note={season.day === today ? "today" : formatDate(season.day)}>
      <p className="mb-3 text-sm">
        <CountUp value={season.count} locale={market.locale} once="season" className="tabular numeral text-3xl font-semibold" />{" "}
        <span className="text-muted-foreground">{season.count === 1 ? "company" : "companies"} reported</span>
      </p>
      <div className="space-y-3">
        <Movers title="Biggest profit rises" rows={season.rises} scale={scale} />
        <Movers title="Biggest profit falls" rows={season.falls} scale={scale} />
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
