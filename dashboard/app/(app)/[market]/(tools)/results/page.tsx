import Link from "next/link";
import type { Metadata } from "next";

import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { LiveSearch } from "@/components/filters/live-search";
import { PageTitle } from "@/components/page-title";
import { Reveal } from "@/components/motion";
import { AutoRefresh } from "@/components/results/auto-refresh";
import { QuarterPicker } from "@/components/results/quarter-picker";
import { ResultCard, type ResultCardData } from "@/components/results/result-card";
import { ResultsLinedUpTile } from "@/components/upcoming/upcoming-tiles";
import { UpcomingButton, UpcomingProvider } from "@/components/upcoming/upcoming-sheet";
import { searchTerm } from "@/lib/concalls.mjs";
import { monthsBefore } from "@/lib/financials.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { formatDate, formatInteger } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getCompanyFacts, getLatestRun } from "@/lib/queries";
import { getUpcoming } from "@/lib/upcoming";
import { getWatchlists } from "@/lib/watchlists";
import {
  getCompanyNames,
  getDeclaredSymbols,
  getLatestResultQuarter,
  getQuarterFilings,
  getQuarterLines,
  getResultFeed,
  type QuarterFiling,
} from "@/lib/results";
import {
  chosenQuarter,
  groupByAnnouncedDay,
  quarterEnds,
  quarterLabel,
  passesGrowth,
  resultCard,
} from "@/lib/results.mjs";
import { isGrowthRule } from "@/lib/event-filters.mjs";

export const metadata: Metadata = { title: "Results" };
export const dynamic = "force-dynamic";

/** Cards per step of "Show more", and the most one page will hold. */
const PAGE_SIZE = 30;
const MAX_SHOWN = 300;
/** Results a growth filter reads before it filters: more than a quarter's NSE filings. */
const GROWTH_SCAN = 4000;
const SEARCH_RESETS = ["shown"];
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
          <p className="text-sm font-medium">Results are available for NSE only.</p>
        </div>
      </div>
    );
  }

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
  const offered = quarterEnds(today);
  const [latest, feed, facts, run] = await Promise.all([
    getLatestResultQuarter(market.code, offered),
    loadFeedFilters(market.code, query, { defaultScope: "all", growth: true }),
    getCompanyFacts(market.code),
    getLatestRun(market.code),
  ]);
  // The newest quarter anyone has filed for: in the first days after a
  // quarter ends nobody has, and an empty page would hide last season.
  const newest = latest ?? offered[0];
  const ended = offered.filter((end) => end <= newest);
  // Only a quarter the picker lists: one nobody has filed for yet would be
  // an empty page under another quarter's label.
  const quarter = chosenQuarter(query.quarter, ended) ?? newest;
  const quarters = ended.map((end) => ({ value: end, label: quarterLabel(end, { fiscal: true }) }));

  const [dated, declaredSymbols, lists] = await Promise.all([
    getUpcoming(market.code, "results", today),
    // The quarter that ended most recently, not `newest`: until someone files for it `newest` is the
    // season before, and its filers are not the ones the upcoming dates belong to.
    getDeclaredSymbols(market.code, offered[0]),
    getWatchlists(market.code),
  ]);
  // A company that has filed is no longer lined up, even while its date is today's.
  // Both figures follow the page's own filter scope (by default the market-cap floor), so the tile
  // reads what the list below and Analysis count.
  const scope = feed.symbols ? new Set(feed.symbols) : null;
  const inScope = (symbol: string) => !scope || scope.has(symbol);
  const declaredInScope = declaredSymbols ? [...declaredSymbols].filter(inScope) : null;
  const upcoming = dated?.filter((row) => inScope(row.symbol) && !declaredSymbols?.has(row.symbol)) ?? null;
  const watchlists = lists.filter((list) => list.symbols.length).map(({ id, name, symbols }) => ({ id, name, symbols }));

  const search = searchTerm(query.q);
  const shown = shownCount(query.shown);
  const filtered = Boolean(search) || !feed.isDefault;

  const periods = [quarter, monthsBefore(quarter, 3), monthsBefore(quarter, 12)];
  const growthRules = feed.filters.rules.filter(isGrowthRule);
  let entries: Awaited<ReturnType<typeof getResultFeed>>["entries"];
  let total: number | null;
  let scanCapped = false;
  if (growthRules.length) {
    // Growth is worked out from the filings, not stored with the feed, so a
    // growth filter reads the whole quarter and keeps what passes; the cards
    // then page through that.
    const [scanned, lines] = await Promise.all([
      getResultFeed(market.code, { quarter, symbols: feed.symbols, search, limit: GROWTH_SCAN }),
      getQuarterLines(market.code, periods, feed.symbols),
    ]);
    scanCapped = scanned.entries.length >= GROWTH_SCAN;
    const filingsOf = new Map<string, QuarterFiling[]>();
    for (const filing of lines) {
      const list = filingsOf.get(filing.symbol) ?? [];
      list.push(filing);
      filingsOf.set(filing.symbol, list);
    }
    const passing = scanned.entries.filter((entry) =>
      passesGrowth(resultCard(entry, filingsOf.get(entry.symbol) ?? [], quarter), growthRules),
    );
    entries = passing.slice(0, shown);
    total = passing.length;
  } else {
    ({ entries, total } = await getResultFeed(market.code, {
      quarter,
      symbols: feed.symbols,
      search,
      limit: shown,
    }));
  }
  const symbols = entries.map((entry) => entry.symbol);
  const [filings, names] = await Promise.all([
    getQuarterFilings(market.code, symbols, periods),
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
        barDate: run?.price_bar_as_of ?? null,
        logoDomain: fact?.logo_domain ?? null,
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

  const page = (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      {/* Only this season's results are still arriving. */}
      {quarter === newest ? <AutoRefresh /> : null}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageTitle
          title="Results"
          info={
            <>
              <p>
                Quarterly results as each company files them with the exchange, within a quarter of an
                hour. Each card sets the quarter against the one before it and the same quarter a year
                earlier.
              </p>
              <p>
                Figures are the company&rsquo;s own, as filed. A company that files on both bases opens on
                its consolidated results, unless only its standalone results reach back a year; changes
                are only taken within one basis. Operating profit is profit before tax with interest and
                depreciation added back. A bank&rsquo;s revenue is net interest income plus other income,
                an insurer&rsquo;s its net premium. There is no growth rate off a loss, and a figure the
                filing did not report is a dash.
              </p>
              {scanCapped ? <p>Growth filters read the latest {formatInteger(GROWTH_SCAN)} results.</p> : null}
            </>
          }
        />
        <div className="flex items-center gap-2">
          {upcoming ? <UpcomingButton /> : null}
          <QuarterPicker value={quarter} options={quarters} />
        </div>
      </div>

      {upcoming?.length ? (
        <div className="flex flex-wrap gap-3">
          <ResultsLinedUpTile
            lined={upcoming.length}
            declared={declaredInScope?.length ?? null}
            soonest={upcoming}
            logos={new Map((facts ?? []).map((fact) => [fact.symbol, fact.logo_domain]))}
          />
        </div>
      ) : null}

      <LiveSearch
        label="Search results by company or symbol"
        placeholder="Search a company or symbol"
        // A longer page of the old list means nothing for a new search.
        resets={SEARCH_RESETS}
        className="max-w-sm"
      />

      <EventFilterBar {...feed.bar} />

      {cards.length ? (
        <Reveal className="space-y-6">
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
                className="inline-flex items-center rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Show more{total === null ? "" : ` · ${formatInteger(cards.length)} of ${formatInteger(total)}`}
              </Link>
            </div>
          ) : null}
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
  return upcoming ? (
    <UpcomingProvider
      kind="results"
      rows={upcoming}
      today={today}
      lists={watchlists}
      defaultOpen={query.upcoming !== undefined}
    >
      {page}
    </UpcomingProvider>
  ) : (
    page
  );
}
