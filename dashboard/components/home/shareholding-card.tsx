import { Change } from "@/components/home/change";
import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { marketToday } from "@/lib/home";
import { getRecentShareholding } from "@/lib/home-watch";
import { shareholdingMoves } from "@/lib/home-watch.mjs";
import { periodLabel } from "@/lib/financials.mjs";
import type { Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";

const SHOWN = 6;
const GROUPS = [
  ["promoter", "Promoter"],
  ["fii", "FII"],
  ["dii", "DII"],
] as const;

/** Watched stocks whose promoter, FII or DII stake moved against the previous quarter. NSE only. */
export async function ShareholdingCard({ market }: { market: Market }) {
  const rows = await getRecentShareholding(market.code, await getWatchedSymbols(market.code), marketToday(market));
  const moves = shareholdingMoves(rows).slice(0, SHOWN);
  if (!moves.length) return null;

  return (
    <HomeCard title="Shareholding moved" note="vs previous quarter, points">
      <ul className="divide-y divide-border">
        {moves.map((move) => (
          <li key={move.symbol} className="flex items-center gap-3 py-2">
            <StockIdentity symbol={move.symbol} company={move.company} subtitle={periodLabel(move.period)} className="min-w-0 flex-1" />
            <span className="tabular flex shrink-0 gap-3 text-xs">
              {GROUPS.map(([key, label]) => (
                <span key={key} className="text-right">
                  <span className="block text-muted-foreground">{label}</span>
                  <Change value={move[key]} unit="" />
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </HomeCard>
  );
}
