import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { AddToWatchlist } from "@/components/watchlist/add-to-watchlist";
import { CompanyLogo } from "@/components/company-logo";
import { SymbolText } from "@/components/symbol-text";
import { LiveChange, LivePrice } from "@/components/live-quote";
import { HistoryBar, NotRatedBadge, listingDetail } from "@/components/new-listing";
import { ZoomIn } from "@/components/motion";
import { Panel } from "@/components/stock/field-list";
import { PriceChart } from "@/components/stock/price-chart";
import { Financials } from "@/components/stock/financials";
import { Shareholding } from "@/components/stock/shareholding";
import { StockTabs } from "@/components/stock/stock-tabs";
import { decodeSeries, withTail } from "@/lib/price-series.mjs";
import { STATUS_LABEL } from "@/lib/new-listings.mjs";
import { formatDate, formatMoneyCompact, formatPercent, MISSING } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type {
  FinancialStatementsRow,
  NewListingRow,
  PriceSeriesRow,
  getPriceTail,
  getShareholding,
} from "@/lib/queries";
import type { getWatchlistMembership, getWatchlists } from "@/lib/watchlists";

/** Gain or loss colour, and none for a return that was not reported. */
function changeTone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "text-positive" : "text-negative";
}

/**
 * The stock page for a company the run has not rated: the scored page's
 * header, stat tiles, chart and tabs, with "Not rated" in the slots a rating
 * or 60 sessions of history would fill.
 */
export function NewListingView({
  listing,
  market,
  financials,
  shareholding,
  watchlists,
  watchlistMembership,
  priceSeries,
  sessions,
  priceTail,
  asOf,
  tab,
}: {
  listing: NewListingRow;
  market: Market;
  financials: FinancialStatementsRow | null;
  shareholding: Awaited<ReturnType<typeof getShareholding>>;
  watchlists: Awaited<ReturnType<typeof getWatchlists>>;
  watchlistMembership: Awaited<ReturnType<typeof getWatchlistMembership>>;
  priceSeries: PriceSeriesRow | null;
  sessions: string[];
  priceTail: Awaited<ReturnType<typeof getPriceTail>>;
  asOf: string | null;
  tab: string;
}) {
  // Same derivation as the scored page's fallback: a listing has no published
  // 1D column, so it comes from the chart's last two closes.
  const points = withTail(decodeSeries(priceSeries, sessions).points, priceTail);
  const change1d =
    points.length >= 2 && points[points.length - 2].close > 0
      ? (points[points.length - 1].close / points[points.length - 2].close - 1) * 100
      : null;
  const change = listing.change_since_first_pct;
  const live = { symbol: listing.symbol, barDate: listing.last_session };
  // Rank, score and anything else that needs a rating or 60 sessions of
  // history read "Not rated" -- never a zero or a dash that looks like a score.
  const notRated = <span className="text-muted-foreground">Not rated</span>;
  const stats = [
    { label: "Rank", value: notRated, tone: "" },
    { label: "Score", value: notRated, tone: "" },
    {
      label: "Price",
      value: <LivePrice {...live} close={listing.last_close} />,
      tone: "",
    },
    {
      label: "1D",
      value: <LiveChange {...live} change={change1d} />,
      tone: "",
    },
    {
      label: "Since first close",
      value: formatPercent(change, 1, true),
      tone: changeTone(change),
    },
    { label: "Market cap", value: formatMoneyCompact(listing.market_cap, market), tone: "" },
  ];

  return (
    <ZoomIn className="space-y-4 px-4 py-5 sm:px-6">
      <div className="panel p-5 sm:p-6">
        <Link
          href={marketPath(market.slug)}
          className="inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          Back to screener
        </Link>

        <div className="mt-3 flex items-center gap-3">
          <CompanyLogo symbol={listing.symbol} domain={listing.logo_domain} size="lg" />
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-mono text-[1.75rem] font-bold leading-tight tracking-tight">
                <SymbolText symbol={listing.symbol} />
              </span>
              <span className="text-heading font-normal text-muted-foreground">
                {listing.company ?? MISSING}
              </span>
            </h1>
            <NotRatedBadge size="md" className="self-center" />
          </div>
          <div className="ml-auto shrink-0 self-start">
            <AddToWatchlist
              symbol={listing.symbol}
              lists={watchlists}
              memberOf={watchlistMembership}
            />
          </div>
        </div>

        <p className="mt-1.5 text-xs text-muted-foreground">
          Listed {formatDate(listing.listed_on)} · Series {listing.series ?? MISSING} · Prices as of{" "}
          {formatDate(listing.last_session ?? asOf)}
        </p>

        <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-row bg-border sm:grid-cols-3 lg:grid-cols-6">
          {stats.map((stat) => (
            <div key={stat.label} className="bg-muted/40 px-4 py-3">
              <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {stat.label}
              </dt>
              <dd className={`tabular mt-0.5 text-lead font-semibold ${stat.tone}`}>{stat.value}</dd>
            </div>
          ))}
        </dl>

        {priceSeries ? (
          <div className="mt-4">
            <PriceChart
              series={priceSeries}
              sessions={sessions}
              tail={priceTail}
              height={300}
              markers={[]}
              live={live}
            />
          </div>
        ) : null}
      </div>

      <StockTabs
        initial={tab}
        tabs={[
          {
            key: "overview",
            label: "Overview",
            content: (
              <Panel title="Rating and factors">
                <div className="rounded-row border border-dashed border-border p-4">
                  <p className="text-sm font-medium">Not rated · {STATUS_LABEL[listing.status]}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {listingDetail(listing, market)} Rating, score, rank and the factor blocks
                    appear once it qualifies.
                  </p>
                  <HistoryBar row={listing} className="mt-3 max-w-sm" />
                </div>
              </Panel>
            ),
          },
          {
            key: "financials",
            label: "Financials",
            content: (
              <Panel
                title="Financials"
                description="As reported so far. A new listing often has only its first one or two quarters at the source."
              >
                <Financials data={financials} market={market} symbol={listing.symbol} asOf={asOf} />
              </Panel>
            ),
          },
          ...(market.code === "NSE"
            ? [
                {
                  key: "shareholding",
                  label: "Shareholding",
                  content: (
                    <Panel title="Shareholding">
                      <Shareholding data={shareholding} market={market} symbol={listing.symbol} />
                    </Panel>
                  ),
                },
              ]
            : []),
        ]}
      />
    </ZoomIn>
  );
}
