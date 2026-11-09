import { Bar } from "@/components/home/bar";
import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate, formatMoneyCompact } from "@/lib/format";
import { marketToday } from "@/lib/home";
import { barScale } from "@/lib/home.mjs";
import { getRecentDeals } from "@/lib/home-watch";
import { dealValue, dealsLag } from "@/lib/home-watch.mjs";
import type { Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";
import { cn } from "@/lib/utils";

const SHOWN = 6;

/**
 * Bulk and block deals in watched stocks over the last week, largest first.
 * The exchange's deal history is loaded by a worker and can run behind, so a
 * late feed says so in the note rather than passing as a quiet week. NSE only.
 */
export async function DealsCard({ market }: { market: Market }) {
  const today = marketToday(market);
  const { deals, newest } = await getRecentDeals(market.code, await getWatchedSymbols(market.code), today);
  if (!deals.length) return null;
  const lag = dealsLag(newest, today);
  const top = [...deals].sort((a, b) => dealValue(b) - dealValue(a)).slice(0, SHOWN);
  const scale = barScale(top.map(dealValue));

  return (
    <HomeCard
      title="Big trades"
      note={lag ? <span className="text-negative">Feed {lag} days behind · latest {formatDate(newest)}</span> : "last 7 days"}
    >
      <ul className="divide-y divide-border">
        {top.map((deal) => {
          const buy = /^b/i.test(deal.side);
          return (
            <li
              key={`${deal.kind}:${deal.deal_date}:${deal.symbol}:${deal.client_name}:${deal.side}:${deal.quantity}:${deal.price}`}
              className="py-2.5"
            >
              <div className="flex items-center gap-3">
                <StockIdentity
                  symbol={deal.symbol}
                  subtitle={`${deal.client_name} · ${formatDate(deal.deal_date)}`}
                  className="min-w-0 flex-1"
                />
                <span className="tabular shrink-0 text-right text-xs">
                  <span className={cn("block font-medium", buy ? "text-positive" : "text-negative")}>
                    {buy ? "Buy" : "Sell"} · {deal.kind}
                  </span>
                  {formatMoneyCompact(dealValue(deal), market)}
                </span>
              </div>
              <Bar value={dealValue(deal)} scale={scale} tone={buy ? "positive" : "negative"} className="mt-1.5" />
            </li>
          );
        })}
      </ul>
    </HomeCard>
  );
}
