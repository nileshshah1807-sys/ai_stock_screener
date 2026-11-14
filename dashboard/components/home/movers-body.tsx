"use client";

import { useState } from "react";

import { QuickWatch } from "@/components/home/quick-watch";
import { shortName, useLiveMarket } from "@/components/market/live-movers";
import { ScrollFade } from "@/components/scroll-fade";
import { SegmentedControl } from "@/components/segmented-control";
import { StockListRow } from "@/components/stock-identity";
import { formatPercent } from "@/lib/format";
import type { MonthlyMovers } from "@/lib/home-market";
import { LIVE_MOVERS_LIMIT, type LiveMarket } from "@/lib/live-market";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

type Window = "1D" | "1M";
type Row = { symbol: string; company: string | null; investment_rank: number | null; change: number };

const SHOWN = 5;

function List({ title, rows, empty }: { title: string; rows: Row[]; empty: string }) {
  return (
    <div>
      <h3 className="pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      {rows.length ? (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.symbol}>
              <StockListRow
                symbol={row.symbol}
                company={row.company}
                // An index member the screener does not rate has no stock page.
                linked={row.investment_rank !== null}
              >
                <span
                  className={cn(
                    "tabular w-16 shrink-0 text-right font-mono text-xs",
                    row.change >= 0 ? "text-positive" : "text-negative",
                  )}
                >
                  {formatPercent(row.change, 2, true)}
                </span>
                <QuickWatch symbol={row.symbol} />
              </StockListRow>
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-3 text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}

/**
 * Gainers and losers of one index over a day (the five-minute quotes, kept
 * current in the browser) or a month (the run's 1M change, read once). A week
 * is not offered: no stored column carries it.
 */
export function MoversBody({
  market,
  initial,
  monthly,
}: {
  market: Market;
  initial: LiveMarket | null;
  monthly: MonthlyMovers;
}) {
  const [window, setWindow] = useState<Window>("1D");
  const [chosen, setChosen] = useState<string | null>(null);
  const { data } = useLiveMarket(market, initial, LIVE_MOVERS_LIMIT);

  const names = data?.indices.map((entry) => entry.name) ?? Object.keys(monthly);
  const name = chosen && names.includes(chosen) ? chosen : names[0];
  const live = data?.indices.find((entry) => entry.name === name);
  const toRows = (rows: { symbol: string; company: string | null; investment_rank: number | null; change_pct: number }[]) =>
    rows.slice(0, SHOWN).map((row) => ({ ...row, change: row.change_pct }));
  const month = monthly[name];
  const gainers = window === "1D" ? toRows(live?.gainers ?? []) : (month?.gainers ?? []).map((row) => ({ ...row, change: row.pct_change_1m }));
  const losers = window === "1D" ? toRows(live?.losers ?? []) : (month?.losers ?? []).map((row) => ({ ...row, change: row.pct_change_1m }));

  if (!name) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No live prices yet today.</p>;
  }
  return (
    <div className="space-y-3">
      <SegmentedControl<Window>
        label="Period"
        value={window}
        onChange={setWindow}
        options={[
          { value: "1D", label: "1D" },
          { value: "1M", label: "1M" },
        ]}
      />
      <ScrollFade>
        <SegmentedControl
          label="Index"
          kind="tabs"
          idPrefix="home-movers"
          value={name}
          onChange={setChosen}
          options={names.map((entry) => ({ value: entry, label: shortName(entry) }))}
        />
      </ScrollFade>
      <div
        role="tabpanel"
        id={`home-movers-panel-${name}`}
        aria-labelledby={`home-movers-tab-${name}`}
        className="space-y-3"
      >
        <List title="Top gainers" rows={gainers} empty={window === "1D" ? "No stock in this index is up today." : "No stock in this index is up over the month."} />
        <List title="Top losers" rows={losers} empty={window === "1D" ? "No stock in this index is down today." : "No stock in this index is down over the month."} />
      </div>
    </div>
  );
}
