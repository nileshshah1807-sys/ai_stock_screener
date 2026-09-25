import type { Metadata } from "next";

import { ReturnsView } from "@/components/returns/returns-view";
import { formatDate } from "@/lib/format";
import { marketFromSlug } from "@/lib/markets";
import { COST_PER_SIDE_PCT, DEFAULT_TOP_N, TOP_N_OPTIONS } from "@/lib/returns.mjs";
import { getReturnsReport } from "@/lib/returns-data";

export const metadata: Metadata = { title: "Returns" };
export const dynamic = "force-dynamic";

function first(value: string | string[] | undefined) {
  return (Array.isArray(value) ? value[0] : value)?.trim() || null;
}

/**
 * Returns: what a past ranking's top N went on to do.
 *
 * Pick a start date and the page takes that day's published ranking, buys its
 * top N at the next session's close in equal weight, and holds them to the
 * latest run -- against the benchmark index and against owning every stock the
 * model ranked that day. Only rankings the dashboard actually published are
 * used, so every figure here is out of sample for the model that made it.
 */
export default async function ReturnsPage({ params, searchParams }: PageProps<"/[market]/returns">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;
  const requestedTop = Number(first(query.top));
  const topN = TOP_N_OPTIONS.includes(requestedTop) ? requestedTop : DEFAULT_TOP_N;
  const costs = first(query.costs) !== "gross";

  const report = await getReturnsReport(market, { from: first(query.from), topN, costs });

  return (
    <div className="space-y-5 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Returns</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          What the screener&rsquo;s top picks went on to return. Choose a past ranking and see its top stocks
          bought the next session and held to today, against the {market.benchmark} and against every stock
          the model ranked that day.
        </p>
      </div>

      {report.status === "no-history" ? (
        <Empty
          title="No rankings on record yet"
          body="Returns can be measured once the daily run has published a ranking and at least one session has closed after it."
        />
      ) : report.status === "too-early" ? (
        <Empty
          title="One ranking so far"
          body={`The only ranking on record is ${formatDate(report.asOf)}. Its stocks can first be bought at the next session's close, so the first return appears after the next run.`}
        />
      ) : (
        <ReturnsView report={report} market={market} />
      )}

      <div className="max-w-3xl space-y-2 border-t pt-4 text-xs leading-relaxed text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">How this is measured.</span> The basket is the top N by
          Investment Rank on the chosen date, in equal weight, bought at each stock&rsquo;s close on the next
          session &mdash; never the close that produced the ranking, which no reader could have traded at. A
          stock that did not trade that session is bought at its first close after it. The basket is held without
          rebalancing; a stock that has since left the universe is kept at its last price rather than dropped.
          Costs, when on, are {COST_PER_SIDE_PCT}% of value on the purchase and again on a sale at the latest
          close.
        </p>
        <p>
          Prices are adjusted for splits and bonuses but not dividends, and the {market.benchmark} is its price
          index, so both sides leave dividends out. &ldquo;All ranked stocks&rdquo; owns every stock ranked that
          day in equal weight over the same sessions. The record starts when the dashboard began storing daily
          rankings, and the model changed during it; the ranking&rsquo;s model is named beside its date.
          Past returns over a few weeks say little about the next few, and the model has not been validated
          out of sample.
        </p>
      </div>
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="panel py-16 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
