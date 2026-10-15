import Link from "next/link";
import type { Metadata } from "next";
import { Search } from "lucide-react";

import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { Reveal } from "@/components/motion";
import { AutoRefresh } from "@/components/results/auto-refresh";
import { QuarterPicker } from "@/components/results/quarter-picker";
import { ResultCard, type ResultCardData } from "@/components/results/result-card";
import { Input } from "@/components/ui/input";
import { searchTerm } from "@/lib/concalls.mjs";
import { monthsBefore } from "@/lib/financials.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { formatDate, formatInteger } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getCompanyFacts } from "@/lib/queries";
import {
  getCompanyNames,
  getLatestResultQuarter,
  getQuarterFilings,
  getResultFeed,
  type QuarterFiling,
} from "@/lib/results";
import {
  chosenQuarter,
  groupByAnnouncedDay,
  quarterEnds,
  quarterLabel,
  resultCard,
} from "@/lib/results.mjs";

export const metadata: Metadata = { title: "Results" };
export const dynamic = "force-dynamic";

/** Cards per step of "Show more", and the most one page will hold. */
const PAGE_SIZE = 30;
const MAX_SHOWN = 300;
/** The exchange files by India's calendar; a result filed at 00:30 IST is that day's. */
const TIME_ZONE = "Asia/Kolkata";

function shownCount(value: string | string[] | undefined) {
  const parsed = Number.parseInt(Array.isArray(value) ? (value[0] ?? "") : (value ?? ""), 10);
  if (!Number.isFinite(parsed) || parsed <= PAGE_SIZE) return PAGE_SIZE;
  return Math.min(MAX_SHOWN, Math.ceil(parsed / PAGE_SIZE) * PAGE_SIZE);
}

/**
 * Quarterly results as the companies file them, newest first, one card per
 * company: the quarter against the one before and the year-ago quarter.
 *
 * Every figure is the company's own filing with the exchange, stored by the
 * Quarterly filings workflow within a quarter of an hour of being filed, and
 * read here as it is stored -- the page re-renders itself every few minutes
 * while it is open, so a result filed this evening appears this evening.
 *
 * Filtered by the bar Notifications and Concalls use (`lib/event-filters.mjs`);
 * the quarter, the filters and the search are all in the URL.
 *
 * NSE only: the US has no exchange filing index.
 */
export default async function ResultsPage({
  params,
  searchParams,
}: PageProps<"/[market]/results">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;
  const base = marketPath(market.slug, "/results");

  if (market.code !== "NSE") {
    return (
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <h1 className="text-title font-semibold">Results</h1>
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">Results are read for NSE only.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {market.label} has no exchange index of results filings to read them from.
          </p>
        </div>
      </div>
    );
  }

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
  const offered = quarterEnds(today);
  const [latest, feed, facts] = await Promise.all([
    getLatestResultQuarter(market.code, offered),
    loadFeedFilters(market.code, query, { defaultScope: "all" }),
    getCompanyFacts(market.code),
  ]);
  // The newest quarter anyone has filed for: in the first days after a
  // quarter ends nobody has, and an empty page would hide last season.
  const newest = latest ?? offered[0];
  const quarter = chosenQuarter(query.quarter, offered) ?? newest;
  const quarters = offered
    .filter((end) => end <= newest)
    .map((end) => ({ value: end, label: quarterLabel(end, { fiscal: true }) }));

  const search = searchTerm(query.q);
  const shown = shownCount(query.shown);
  const filtered = Boolean(search) || !feed.isDefault;

  const { entries, total } = await getResultFeed(market.code, {
    quarter,
    symbols: feed.symbols,
    search,
    limit: shown,
  });
  const symbols = entries.map((entry) => entry.symbol);
  const [filings, names] = await Promise.all([
    getQuarterFilings(market.code, symbols, [quarter, monthsBefore(quarter, 3), monthsBefore(quarter, 12)]),
    getCompanyNames(
      market.code,
      entries.filter((entry) => !entry.company).map((entry) => entry.symbol),
    ),
  ]);

  const bySymbol = new Map<string, QuarterFiling[]>();
  for (const filing of filings) {
    const list = bySymbol.get(filing.symbol) ?? [];
    list.push(filing);
    bySymbol.set(filing.symbol, list);
  }
  const factsBySymbol = new Map((facts ?? []).map((fact) => [fact.symbol, fact]));

  const cards = entries
    .map((entry) => {
      const card = resultCard(entry, bySymbol.get(entry.symbol) ?? [], quarter);
      const fact = factsBySymbol.get(entry.symbol);
      return {
        ...card,
        company: entry.company ?? names.get(entry.symbol) ?? null,
        marketCap: fact?.market_cap ?? null,
        pe: fact?.pe_ratio ?? null,
      };
    })
    .filter((card) => card.bases.length > 0);
  const groups = groupByAnnouncedDay(cards, TIME_ZONE) as {
    date: string;
    entries: (ResultCardData & { announced_at: string | null })[];
  }[];

  const more = entries.length === shown && shown < MAX_SHOWN && (total === null || total > shown);
  const moreParams = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : value ? [value] : []) moreParams.append(key, item);
  }
  moreParams.set("shown", String(shown + PAGE_SIZE));

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      {/* Only this season's results are still arriving. */}
      {quarter === newest ? <AutoRefresh /> : null}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-title font-semibold">Results</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Quarterly results the evening they are filed, from each company&rsquo;s own filing with the
            exchange. Each card sets the quarter against the one before it and the same quarter a year
            earlier.
          </p>
        </div>
        <QuarterPicker value={quarter} options={quarters} />
      </div>

      {/*
        A plain GET form, as on Concalls: the search is part of the URL like
        every other filter, so a result can be bookmarked. The hidden fields
        carry the quarter and the filters already chosen through the submit.
      */}
      <form action={base} method="get" role="search" className="relative max-w-sm">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          name="q"
          defaultValue={search}
          placeholder="Search a company or symbol"
          aria-label="Search results by company or symbol"
          autoComplete="off"
          className="pl-10"
        />
        {quarter !== newest ? <input type="hidden" name="quarter" value={quarter} /> : null}
        {feed.entries.map(([name, value]) => (
          <input key={`${name}:${value}`} type="hidden" name={name} value={value} />
        ))}
      </form>

      <EventFilterBar {...feed.bar} />

      {cards.length ? (
        <Reveal className="space-y-6">
          <p className="tabular text-xs text-muted-foreground">
            {total === null
              ? `Showing the latest ${formatInteger(cards.length)} results`
              : `Showing ${formatInteger(cards.length)} of ${formatInteger(total)} results`}{" "}
            for {quarterLabel(quarter, { fiscal: true })}
          </p>
          {groups.map((group) => (
            <section key={group.date} aria-labelledby={`results-${group.date}`} className="space-y-3">
              <h2
                id={`results-${group.date}`}
                className="flex items-center gap-2 text-base font-semibold tracking-[-0.011em]"
              >
                {group.date ? formatDate(group.date) : "Date not given"}
                <span className="tabular font-mono text-xs font-normal text-muted-foreground">
                  {group.entries.length}
                </span>
              </h2>
              <div className="grid gap-4 xl:grid-cols-2">
                {group.entries.map((card) => (
                  <ResultCard key={card.symbol} card={card} />
                ))}
              </div>
            </section>
          ))}
          {more ? (
            <div className="text-center">
              <Link
                href={`${base}?${moreParams.toString()}`}
                scroll={false}
                className="inline-flex items-center rounded-full border px-4 py-2 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Show more results
              </Link>
            </div>
          ) : null}
          <p className="max-w-3xl border-t pt-4 text-xs leading-relaxed text-muted-foreground">
            Figures are the company&rsquo;s own, as filed; a company that files on both bases opens
            on its consolidated results, and changes are only ever taken within one basis. Operating
            profit is profit before tax with interest and depreciation added back, as on the stock
            page. There is no growth rate off a loss, and a figure the filing did not report is a
            dash. Banks and insurers file a different statement and are not shown yet.
          </p>
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">
            {search
              ? `No results match “${search}” for ${quarterLabel(quarter)}.`
              : feed.scoped
                ? `None of the companies on your watchlists has filed for ${quarterLabel(quarter)} yet.`
                : feed.isDefault
                  ? `No results filed for ${quarterLabel(quarter)} yet.`
                  : "No results match these filters."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Results appear here within a quarter of an hour of being filed with the exchange.
          </p>
          {filtered ? (
            <Link
              href={quarter === newest ? base : `${base}?quarter=${quarter}`}
              className="mt-3 inline-block rounded text-xs font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Clear search and filters
            </Link>
          ) : null}
        </div>
      )}
    </div>
  );
}
