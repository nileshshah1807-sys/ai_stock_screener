import { Fragment } from "react";

import { DivBar } from "@/components/home/bar";
import { Change } from "@/components/home/change";
import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { marketToday } from "@/lib/home";
import { barScale } from "@/lib/home.mjs";
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

  const scale = barScale(moves.flatMap((move) => GROUPS.map(([key]) => move[key])));

  return (
    <HomeCard title="Shareholding moved" note="vs previous quarter, points">
      <ul className="divide-y divide-border">
        {moves.map((move) => (
          <li key={move.symbol} className="py-2.5">
            <StockIdentity symbol={move.symbol} company={move.company} subtitle={periodLabel(move.period)} />
            <dl className="mt-2 grid grid-cols-[3.5rem_minmax(0,1fr)_3.25rem] items-center gap-x-2 gap-y-1.5 text-xs">
              {GROUPS.map(([key, label]) => (
                <Fragment key={key}>
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd><DivBar value={move[key]} scale={scale} /></dd>
                  <dd className="text-right"><Change value={move[key]} unit="" /></dd>
                </Fragment>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </HomeCard>
  );
}
