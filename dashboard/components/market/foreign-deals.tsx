import { Bar } from "@/components/home/bar";
import { flowFormat } from "@/components/market/flow-format";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate } from "@/lib/format";
import { barScale } from "@/lib/home.mjs";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

type Deal = { client: string; symbol: string; company?: string | null; net: number; first?: string; last?: string };

/** "3 Nov" or "3 – 9 Nov 2026" style span of a client's deals in one stock. */
function span(first?: string, last?: string) {
  if (!first) return "";
  return !last || first === last ? formatDate(first) : `${formatDate(first)} – ${formatDate(last)}`;
}

/**
 * The largest foreign deals per stock over the last 30 days: bulk and block
 * deals by clients workers/fpi_flows.py reads as foreign, netted per client
 * and stock, five bought and five sold.
 */
export function ForeignDeals({
  market,
  deals,
}: {
  market: Market;
  deals: { bought: Deal[]; sold: Deal[]; since: string | null };
}) {
  const { signed, tone } = flowFormat(market);
  const scale = barScale([...deals.bought, ...deals.sold].map((deal) => deal.net));

  const side = (title: string, rows: Deal[], empty: string) => (
    <div className="panel p-4 sm:p-5">
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.length ? (
        <ol className="mt-2 divide-y divide-border/60">
          {rows.map((deal) => (
            <li key={`${deal.client}:${deal.symbol}`} className="py-2.5">
              <div className="flex items-center gap-3">
                <StockIdentity
                  symbol={deal.symbol}
                  company={deal.company}
                  emphasis="company"
                  className="min-w-0 flex-1"
                />
                <span className="tabular shrink-0 text-right text-xs">
                  <span className={cn("block font-mono font-semibold", tone(deal.net))}>{signed(deal.net)}</span>
                  <span className="text-muted-foreground">{span(deal.first, deal.last)}</span>
                </span>
              </div>
              <p className="mt-1.5 truncate text-xs text-muted-foreground" title={deal.client}>
                {deal.client}
              </p>
              <Bar value={deal.net} scale={scale} tone={deal.net >= 0 ? "positive" : "negative"} className="mt-1.5" />
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );

  return (
    <section aria-labelledby="foreign-deals-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="foreign-deals-title" className="text-lead font-semibold tracking-[-0.011em]">
          Largest foreign deals
        </h2>
        <p className="tabular text-xs text-muted-foreground">
          Bulk &amp; block{deals.since ? ` · since ${formatDate(deals.since)}` : ""}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {side("Bought", deals.bought, "No foreign buying in bulk or block deals in the last 30 days.")}
        {side("Sold", deals.sold, "No foreign selling in bulk or block deals in the last 30 days.")}
      </div>
    </section>
  );
}
