import type { Metadata } from "next";
import { ChevronRight } from "lucide-react";

import { ReturnsView } from "@/components/returns/returns-view";
import { formatDate } from "@/lib/format";
import { marketFromSlug } from "@/lib/markets";
import { COST_PER_SIDE_PCT, DEFAULT_TOP_N, INVESTED_OPTIONS, STOP_OPTIONS, SIZE_PICK_MARKETS, TOP_N_OPTIONS, pickKey } from "@/lib/returns.mjs";
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
 * top N at the next session's close in equal slices, and holds them to the
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
  // Three filters, `rating`, `stage` and `size`; a link from before they split carries
  // one `pick` value, which is still a valid key.
  const rating = first(query.rating);
  const stage = first(query.stage);
  // A size floor is offered only where the market has one.
  const size = SIZE_PICK_MARKETS.includes(market.code) ? first(query.size) : undefined;
  const pick = rating || stage || size ? pickKey(rating, stage, size) : first(query.pick);

  const report = await getReturnsReport(market, {
    from: first(query.from),
    topN,
    costs,
    rebalance: first(query.rebalance),
    pick,
    weights: first(query.weights),
    investedPct: INVESTED_OPTIONS.includes(Number(first(query.invested)))
      ? Number(first(query.invested))
      : 100,
    stopPct: STOP_OPTIONS.find((option) => option.value === first(query.stop))?.pct ?? null,
  });

  return (
    <div className="space-y-5 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Returns</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          What the screener&rsquo;s picks went on to return, against the {market.benchmark}.
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

      <details className="group max-w-3xl border-t pt-3 text-xs leading-relaxed text-muted-foreground">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded font-medium text-foreground select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="size-3.5 text-muted-foreground transition-transform duration-(--duration-fast) group-open:rotate-90"
            aria-hidden
          />
          How this is measured
        </summary>
        <div className="mt-2 space-y-2 pl-5">
          <p>
            The basket is the top N by
            Investment Rank on the chosen date, in equal slices, bought at each stock&rsquo;s close on the next
            session &mdash; never the close that produced the ranking, which no reader could have traded at. A
            stock that did not trade that session is bought at its first close after it. With rebalancing off the
            basket is held as bought. With it on, at each step the stocks that no longer qualify are sold and
            their slots refilled from that day&rsquo;s ranking with the sale money, again at the next
            session&rsquo;s close. A stock that is kept is never trimmed or topped up, so a winner is left to run,
            and a slot nothing qualified for waits in cash &mdash; unless &ldquo;Reset to equal&rdquo; is chosen,
            which also trims every winner and tops up every loser back to an equal share at each rebalance. With a
            rating and a stage filter together, a stock is bought when it passes both and sold once it fails
            either&rsquo;s hold rule. With the stop loss on, a holding that closes 20% below its highest close
            since purchase is also sold, at the next close, and its money waits for the next rebalance. A stock that has since left the universe is kept at its
            last price rather than dropped. Costs, when on, are {COST_PER_SIDE_PCT}% of the value traded &mdash; on
            each purchase, each sale and a final sale at the latest close.
          </p>
          <p>
            Prices are adjusted for splits and bonuses but not dividends, and the {market.benchmark} is its price
            index, so both sides leave dividends out. &ldquo;All ranked stocks&rdquo; is an equal-weight index of
            every stock the model ranked, rebalanced daily. Published rankings start when the dashboard began
            storing them; earlier dates use point-in-time backtest rankings, reconstructed with today&rsquo;s
            weights over the period those weights were fitted on, and are marked as such. The model changed during
            the live record too; each ranking&rsquo;s model is named beside its date. Past returns say little about
            future ones, and the model has not been validated out of sample.
          </p>
        </div>
      </details>
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
