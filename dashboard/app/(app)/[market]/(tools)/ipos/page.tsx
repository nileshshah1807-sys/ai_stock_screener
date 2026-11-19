import Link from "next/link";
import type { Metadata } from "next";

import { IpoRow, ListedRow, LiveDot } from "@/components/ipos/ipo-row";
import { PageTitle } from "@/components/page-title";
import { Reveal } from "@/components/motion";
import { formatDateTimeIST } from "@/lib/format";
import { getIpos, getPricesNow, type Ipo } from "@/lib/ipos";
import { groupIssues } from "@/lib/ipos.mjs";
import { marketFromSlug, marketPath, type Market } from "@/lib/markets";

export const metadata: Metadata = { title: "IPOs" };
export const dynamic = "force-dynamic";

/** Listed issues shown before "Show all": the last two months or so of listings. */
const LISTED_SHOWN = 40;

const SECTIONS = [
  { key: "bidding", title: "Bidding now" },
  { key: "upcoming", title: "Upcoming" },
  { key: "awaiting", title: "Awaiting listing" },
] as const;

function Section({
  title,
  count,
  live,
  children,
}: {
  title: string;
  count: number;
  live?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="panel overflow-hidden">
      <h2 className="flex items-center gap-2 border-b px-4 py-3 text-base font-semibold tracking-[-0.011em]">
        {live ? <LiveDot /> : null}
        {title}
        <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">{count}</span>
      </h2>
      {children}
    </section>
  );
}

function ListedTable({ rows, market, prices }: { rows: Ipo[]; market: Market; prices: Map<string, number> }) {
  const head = "px-3 py-2 text-right font-medium";
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Issues listed in the last year: listing-day open and close against the issue price, and the price now
        </caption>
        <thead>
          <tr className="whitespace-nowrap border-b text-[11px] text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium">Company</th>
            <th scope="col" className={`${head} hidden sm:table-cell`}>Listed</th>
            <th scope="col" className={`${head} hidden sm:table-cell`}>Issue price</th>
            <th scope="col" className={head}>Listing open</th>
            <th scope="col" className={`${head} hidden md:table-cell`}>Day&rsquo;s close</th>
            <th scope="col" className={`${head} hidden lg:table-cell`}>Subscribed</th>
            <th scope="col" className={head}>Now</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ListedRow key={row.symbol} row={row} market={market} now={prices.get(row.symbol) ?? null} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * NSE's IPOs: what is bidding, what opens next, what has closed and waits to
 * list, and how the last year's issues listed and trade now.
 *
 * Everything is the exchange's own record, stored by the Quarterly filings
 * workflow every quarter of an hour (workers/ipos.py) and read here from one
 * object. The grey-market premium is the one figure that is not: it is shown
 * only when the GMP source is switched on, and labelled unofficial wherever it
 * appears. Nothing on this page is a rating.
 */
export default async function IposPage({ params, searchParams }: PageProps<"/[market]/ipos">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  if (market.code !== "NSE") {
    return (
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <h1 className="text-title font-semibold">IPOs</h1>
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">Coming soon</p>
          <p className="mt-1 text-xs text-muted-foreground">IPOs are read from NSE; there is no US source yet.</p>
        </div>
      </div>
    );
  }

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: market.timezone }).format(new Date());
  const rows = (await getIpos(market.code)) ?? [];
  const groups = groupIssues(rows, today) as Record<"bidding" | "upcoming" | "awaiting" | "listed", Ipo[]>;
  const showAll = query.listed === "all";
  const listed = showAll ? groups.listed : groups.listed.slice(0, LISTED_SHOWN);
  const prices = await getPricesNow(market.code, listed.map((row) => row.symbol));
  const live = SECTIONS.filter(({ key }) => groups[key].length);
  const bookTime = groups.bidding.map((row) => row.subscription_as_of).filter(Boolean).sort().at(-1) ?? null;

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <PageTitle
        title="IPOs"
        info={
          <>
            <p>
              NSE&rsquo;s mainboard and SME issues: what is bidding now, what opens next, what has closed and
              waits to list, and how every issue of the last year listed. Issues on BSE&rsquo;s SME platform
              alone are not here, as NSE does not list them.
            </p>
            <p>
              Subscription is the exchanges&rsquo; combined NSE and BSE book: shares bid for over shares
              reserved, by investor category, refreshed every quarter of an hour while bidding. The book size
              excludes the anchor portion. Listing open is the price the listing day&rsquo;s opening auction
              found; changes are against the issue price.
            </p>
            <p>
              GMP, the grey-market premium, is an unofficial price for the shares before they list, as a
              public tracker reports it. No exchange publishes it and it is not a forecast.
            </p>
          </>
        }
      />

      {!rows.length ? (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">No issues to show yet.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The list fills on the next run of the Quarterly filings workflow.
          </p>
        </div>
      ) : (
        <Reveal className="space-y-4">
          {live.length ? (
            live.map(({ key, title }) => (
              <Section key={key} title={title} count={groups[key].length} live={key === "bidding"}>
                <ul className="divide-y">
                  {groups[key].map((row) => (
                    <li key={row.symbol}>
                      <IpoRow row={row} market={market} today={today} />
                    </li>
                  ))}
                </ul>
                {key === "bidding" && bookTime ? (
                  <p className="tabular border-t px-4 py-2 text-[11px] text-muted-foreground">
                    Book as at {formatDateTimeIST(bookTime)}
                  </p>
                ) : null}
              </Section>
            ))
          ) : (
            <div className="panel px-5 py-8 text-center">
              <p className="text-sm font-medium">No issue is bidding or announced right now.</p>
            </div>
          )}

          {groups.listed.length ? (
            <Section title="Listed in the last year" count={groups.listed.length}>
              <ListedTable rows={listed} market={market} prices={prices} />
              {groups.listed.length > listed.length ? (
                <div className="border-t px-4 py-2.5 text-center">
                  <Link
                    prefetch={false}
                    href={`${marketPath(market.slug, "/ipos")}?listed=all`}
                    className="rounded text-xs font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Show all {groups.listed.length}
                  </Link>
                </div>
              ) : null}
            </Section>
          ) : null}
        </Reveal>
      )}
    </div>
  );
}
