"use client";

import Link from "next/link";
import { useState } from "react";

import { formatDate, formatPercent } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type { TradeRound } from "@/lib/returns-data";
import { cn } from "@/lib/utils";

/** Rounds shown at first, and added per "show more". */
const FIRST_PAGE = 12;
const NEXT_PAGE = 24;

/**
 * Every round of a rebalanced basket, newest first: what was bought and sold,
 * which ranking it came from, and what the basket did until the next round.
 *
 * The Holdings table answers "what do I own now"; this answers "what did I
 * trade to get here". A round's return is the basket's own move from that
 * round to the next, so the rounds compound to the headline figure before
 * costs, and each round's trading cost sits beside it rather than inside it.
 *
 * Rounds are blocks rather than table rows because the bought and sold lists
 * vary from none to fifty names: a table would either truncate them or give
 * every row the height of the longest.
 */
export function TradeLog({ trades, market }: { trades: TradeRound[]; market: Market }) {
  const [shown, setShown] = useState(FIRST_PAGE);
  const newestFirst = [...trades].reverse();
  const visible = newestFirst.slice(0, shown);
  const remaining = newestFirst.length - visible.length;

  return (
    <section className="panel overflow-hidden">
      <div className="border-b px-4 py-3">
        <h2 className="text-base font-semibold tracking-[-0.011em]">Trade log</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {trades.length} {trades.length === 1 ? "round" : "rounds"}, newest first. Each return is the basket&rsquo;s
          move until the next round; its trading cost is shown separately.
        </p>
      </div>
      <ol className="divide-y">
        {visible.map((trade, index) => {
          const initial = index === newestFirst.length - 1;
          return (
            <li key={trade.entrySession} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-sm font-semibold">{formatDate(trade.entrySession)}</span>
                <span className="text-xs text-muted-foreground">
                  {initial ? "Initial purchase" : "Rebalance"} &middot; ranking of {formatDate(trade.rankDate)}
                </span>
                {trade.backtest ? (
                  <span className="rounded-full border border-caution/40 bg-caution/10 px-2 py-px text-[10px] font-medium text-caution">
                    backtest
                  </span>
                ) : null}
                <span className="ml-auto flex items-baseline gap-3">
                  <span className="text-[11px] text-muted-foreground">
                    to {formatDate(trade.periodEnd)}
                    {trade.costPct > 0 ? ` · cost ${trade.costPct.toFixed(2)} pts` : ""}
                  </span>
                  <span
                    className={cn(
                      "tabular font-mono text-sm font-semibold",
                      trade.returnPct === null
                        ? "text-muted-foreground"
                        : trade.returnPct >= 0
                          ? "text-positive"
                          : "text-negative",
                    )}
                  >
                    {formatPercent(trade.returnPct, 2, true)}
                  </span>
                </span>
              </div>
              {trade.bought.length || trade.sold.length ? (
                <dl className="mt-2 space-y-1 text-xs">
                  <Names label="Bought" symbols={trade.bought} market={market} tone="text-positive" />
                  <Names label="Sold" symbols={trade.sold} market={market} tone="text-negative" />
                </dl>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">
                  Same names as before; weights reset to equal.
                </p>
              )}
            </li>
          );
        })}
      </ol>
      {remaining > 0 ? (
        <div className="border-t px-4 py-2">
          <button
            type="button"
            onClick={() => setShown((count) => count + NEXT_PAGE)}
            className="rounded-full px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Show {Math.min(NEXT_PAGE, remaining)} earlier {Math.min(NEXT_PAGE, remaining) === 1 ? "round" : "rounds"}{" "}
            ({remaining} left)
          </button>
        </div>
      ) : null}
    </section>
  );
}

function Names({
  label,
  symbols,
  market,
  tone,
}: {
  label: string;
  symbols: string[];
  market: Market;
  tone: string;
}) {
  if (!symbols.length) return null;
  return (
    <div className="flex gap-2">
      <dt className={cn("w-16 shrink-0 font-medium", tone)}>
        {label} {symbols.length}
      </dt>
      <dd className="flex min-w-0 flex-wrap gap-x-2 gap-y-0.5">
        {symbols.map((symbol) => (
          <Link
            key={symbol}
            href={marketPath(market.slug, `/stocks/${encodeURIComponent(symbol)}`)}
            // Off, as in the holdings table: a long log would otherwise
            // prefetch dozens of stock pages nobody opens.
            prefetch={false}
            className="font-mono underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {symbol}
          </Link>
        ))}
      </dd>
    </div>
  );
}
