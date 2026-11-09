import { HomeCard } from "@/components/home/home-card";
import { WatchRow } from "@/components/home/watch-row";
import { getRecentCloses } from "@/lib/home-watch";
import type { Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";

/** Storage reads are one object a stock, so the card shows the first dozen of a long list. */
const SHOWN = 12;

/** Live 1D, 1W and 1M for the watched stocks, each with a month's trend line. */
export async function WatchlistTodayCard({ market }: { market: Market }) {
  const symbols = (await getWatchedSymbols(market.code)).slice(0, SHOWN);
  if (!symbols.length) return null;
  const closes = await Promise.all(symbols.map((symbol) => getRecentCloses(market.code, symbol)));

  return (
    <HomeCard title="Your watchlist today" note="live">
      <ul className="divide-y divide-border">
        {symbols.map((symbol, index) => (
          <WatchRow key={symbol} symbol={symbol} closes={closes[index].slice(-60)} />
        ))}
      </ul>
    </HomeCard>
  );
}
