"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import { CompanyLogo } from "@/components/company-logo";
import { RatingBadge } from "@/components/rating-badge";
import { SegmentedControl } from "@/components/segmented-control";
import { formatDate, formatMoney, formatPercent, MISSING } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { modelForDate } from "@/lib/returns.mjs";
import type { ClosedTrade, HoldingRow, TradeRound } from "@/lib/returns-data";
import { STAGES } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "holdings" | "closed" | "history";
type ClosedOrder = "recent" | "best" | "worst";

/** Closed positions shown at first, and added per "show more". */
const CLOSED_PAGE = 25;

/** Rounds shown at first, and added per "show earlier". */
const FIRST_PAGE = 12;
const NEXT_PAGE = 24;
/** Names shown per bought or sold line before "+N more". */
const NAMES_SHOWN = 6;

const STAGE_TONE: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  caution: "text-caution",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
};

/**
 * What the basket holds and how it got there, as one panel with two views.
 *
 * Three questions, one panel. Holdings: what do I own now (each return runs
 * from that stock's purchase). Closed: what did I own, and how did each
 * position do from buy to sell. Rebalances: when did the basket change, and
 * what did it do between changes (each return is the whole basket's). They
 * were separate stacked panels, which read as competing answers to one
 * question; a segmented switch shows one at a time, and each view says in one
 * line what its numbers measure.
 *
 * History appears only once there is a history: a basket bought once and held
 * has a single round, which the holdings already describe.
 */
export function Portfolio({
  holdings,
  trades,
  closed,
  market,
  topN,
  lastRankDate,
  firstEntry,
  rebalances,
  swapped,
  costPct,
}: {
  holdings: HoldingRow[];
  trades: TradeRound[];
  closed: ClosedTrade[];
  market: Market;
  topN: number;
  lastRankDate: string;
  firstEntry: string;
  rebalances: number;
  swapped: number;
  costPct: number;
}) {
  const [tab, setTab] = useState<Tab>("holdings");
  const hasHistory = trades.length > 1;
  const view = hasHistory ? tab : "holdings";
  const priced = holdings.filter((row) => row.returnPct !== null);
  const winners = priced.filter((row) => row.returnPct! > 0).length;

  return (
    <section className="panel overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <h2 className="text-base font-semibold tracking-[-0.011em]">Portfolio</h2>
        {hasHistory ? (
          <SegmentedControl
            label="Portfolio view"
            kind="tabs"
            idPrefix="portfolio"
            value={tab}
            onChange={setTab}
            options={[
              {
                value: "holdings",
                label: (
                  <>
                    Holdings <span className="ml-1 font-normal text-muted-foreground tabular">{holdings.length}</span>
                  </>
                ),
              },
              {
                value: "closed",
                label: (
                  <>
                    Closed <span className="ml-1 font-normal text-muted-foreground tabular">{closed.length}</span>
                  </>
                ),
              },
              {
                value: "history",
                label: (
                  <>
                    Rebalances <span className="ml-1 font-normal text-muted-foreground tabular">{rebalances}</span>
                  </>
                ),
              },
            ]}
          />
        ) : null}
      </header>

      <div
        // Re-keyed per view so the new one fades in rather than swapping hard.
        key={view}
        role={hasHistory ? "tabpanel" : undefined}
        id={hasHistory ? `portfolio-panel-${view}` : undefined}
        aria-labelledby={hasHistory ? `portfolio-tab-${view}` : undefined}
        className="animate-fade"
      >
        {view === "holdings" ? (
          <>
            <p className="px-4 pt-3 text-xs text-muted-foreground">
              {winners} of {priced.length} up. Each return runs from the day that stock was bought.
              {hasHistory
                ? ` These are the stocks held after the last rebalance, on the ${formatDate(lastRankDate)} ranking.`
                : ` Bought once and held, so a stock that has since left the top ${topN} is still here.`}
            </p>
            <HoldingsTable holdings={holdings} market={market} topN={topN} firstEntry={firstEntry} />
          </>
        ) : view === "closed" ? (
          <Closed trades={closed} market={market} />
        ) : (
          <History trades={trades} market={market} swapped={swapped} costPct={costPct} />
        )}
      </div>
    </section>
  );
}

function StageText({ stage }: { stage: string | null }) {
  const meta = STAGES.find((item) => item.value === stage);
  if (!meta) return <span className="text-muted-foreground">{MISSING}</span>;
  return (
    <span title={meta.meaning} className={cn("font-mono text-xs font-semibold", STAGE_TONE[meta.tone])}>
      {meta.short}
    </span>
  );
}

/**
 * Stage now, and where it came from only when that is known and different.
 * "S2 → S2" says nothing, and "— → S2" reads like a fault: past stages have
 * been recorded only since 2026-09-18.
 */
function StageChange({ then, now }: { then: string | null; now: string | null }) {
  if (!then || then === now) return <StageText stage={now} />;
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <StageText stage={then} />
      <span aria-label="became">→</span>
      <StageText stage={now} />
    </span>
  );
}

function ReturnText({ value, size = "xs" }: { value: number | null; size?: "xs" | "sm" }) {
  if (value === null) return <span className="text-muted-foreground">{MISSING}</span>;
  return (
    <span
      className={cn(
        "tabular font-mono font-semibold",
        size === "sm" ? "text-sm" : "text-xs",
        value >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {formatPercent(value, 2, true)}
    </span>
  );
}

function RankNow({ row, topN }: { row: HoldingRow; topN: number }) {
  if (!row.inLatestRun || row.rankNow === null) {
    return <span className="whitespace-nowrap text-[11px] text-muted-foreground">not ranked</span>;
  }
  const change = row.rankThen !== null ? row.rankThen - row.rankNow : 0;
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn("tabular font-mono text-xs", row.rankNow > topN && "text-muted-foreground")}>
        {row.rankNow}
      </span>
      {change ? (
        <span
          className={cn(
            "tabular inline-flex items-center font-mono text-[11px]",
            change > 0 ? "text-positive" : "text-negative",
          )}
        >
          {change > 0 ? <ArrowUpRight className="size-3" aria-hidden /> : <ArrowDownRight className="size-3" aria-hidden />}
          {Math.abs(change)}
        </span>
      ) : null}
    </span>
  );
}

function HoldingsTable({
  holdings,
  market,
  topN,
  firstEntry,
}: {
  holdings: HoldingRow[];
  market: Market;
  topN: number;
  firstEntry: string;
}) {
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full text-sm sm:min-w-[640px]">
        <thead>
          <tr className="border-y text-left text-[11px] font-medium text-muted-foreground">
            <th className="px-4 py-2 font-medium">#</th>
            <th className="px-2 py-2 font-medium">Stock</th>
            <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Bought at</th>
            <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Latest</th>
            <th className="px-2 py-2 text-right font-medium">Return</th>
            <th className="px-2 py-2 font-medium">Rank now</th>
            <th className="hidden px-2 py-2 font-medium sm:table-cell">Stage</th>
            <th className="px-4 py-2 font-medium">Rating now</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {holdings.map((row) => (
            <tr key={row.symbol} className="hover:bg-muted/50">
              <td className="tabular px-4 py-2 font-mono text-xs text-muted-foreground">{row.rankThen ?? MISSING}</td>
              <td className="max-w-[18rem] px-2 py-2">
                <Link
                  href={marketPath(market.slug, `/stocks/${encodeURIComponent(row.symbol)}`)}
                  // Off, as in the screener grid: up to 50 rows would each
                  // prefetch a stock page the reader will mostly never open.
                  prefetch={false}
                  className="group flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <CompanyLogo symbol={row.symbol} domain={row.logoDomain} />
                  <span className="min-w-0">
                    <span className="block font-mono text-xs font-semibold underline-offset-2 group-hover:underline">
                      {row.symbol}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground">{row.company ?? MISSING}</span>
                  </span>
                </Link>
              </td>
              <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                {row.entry ? formatMoney(row.entry.close, market, market.listPriceDigits) : MISSING}
                {row.delayedEntry && row.entry ? (
                  <span className="block whitespace-nowrap text-[10px] text-caution" title="Did not trade on the entry session">
                    on {formatDate(row.entry.time)}
                  </span>
                ) : row.entry && row.heldSince && row.heldSince !== firstEntry ? (
                  <span className="block whitespace-nowrap text-[10px] text-muted-foreground">
                    on {formatDate(row.heldSince)}
                  </span>
                ) : null}
              </td>
              <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                {row.last ? formatMoney(row.last.close, market, market.listPriceDigits) : MISSING}
              </td>
              <td className="px-2 py-2 text-right">
                <ReturnText value={row.returnPct} />
              </td>
              <td className="px-2 py-2">
                <RankNow row={row} topN={topN} />
              </td>
              <td className="hidden px-2 py-2 sm:table-cell">
                <StageChange then={row.stageThen} now={row.stageNow} />
              </td>
              <td className="px-4 py-2">
                {row.ratingNow ? <RatingBadge rating={row.ratingNow} /> : <span className="text-muted-foreground">{MISSING}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The rebalances, newest first, grouped by where each round's ranking came
 * from -- a published ranking of a given model, or the backtest. A group that
 * follows a different one says so: the first round after a model change swaps
 * most of the basket because the ranking method changed, not the market.
 */
function History({
  trades,
  market,
  swapped,
  costPct,
}: {
  trades: TradeRound[];
  market: Market;
  swapped: number;
  costPct: number;
}) {
  const [shown, setShown] = useState(FIRST_PAGE);
  const newestFirst = [...trades].reverse();
  const visible = newestFirst.slice(0, shown);
  const remaining = newestFirst.length - visible.length;
  const model = (trade: TradeRound) =>
    trade.backtest ? "Model 5.1" : (modelForDate(market.code, trade.rankDate) ?? "an unknown model");
  // The group heading, and the same source as it reads inside a sentence.
  const source = (trade: TradeRound) => `${trade.backtest ? "Backtest" : "Published"} · ${model(trade)}`;
  const phrase = (trade: TradeRound) =>
    trade.backtest ? `backtest rankings (${model(trade)})` : `published ${model(trade)} rankings`;

  return (
    <>
      <p className="px-4 pt-3 pb-1 text-xs text-muted-foreground">
        {trades.length - 1} {trades.length === 2 ? "rebalance" : "rebalances"}, {swapped}{" "}
        {swapped === 1 ? "stock" : "stocks"} swapped, {costPct.toFixed(2)} pts of trading costs. Each return is the
        whole basket&rsquo;s move until the next rebalance.
      </p>
      <ol>
        {visible.map((trade, index) => {
          const group = source(trade);
          const newer = index > 0 ? source(visible[index - 1]) : null;
          const previous = newestFirst[index + 1];
          // The oldest round of a group is where the ranking method changed.
          const switched = previous && source(previous) !== group ? phrase(previous) : null;
          return (
            <li key={trade.entrySession}>
              {group !== newer ? (
                <div className={cn("bg-muted/40 px-4 py-1.5", index > 0 && "border-t")}>
                  <p className="text-[11px] font-semibold tracking-[0.02em] text-muted-foreground uppercase">
                    {group}
                  </p>
                </div>
              ) : null}
              <Round
                trade={trade}
                market={market}
                initial={index === newestFirst.length - 1}
                switchedFrom={switched ? `${switched} to ${phrase(trade)}` : null}
                divided={group === newer}
              />
            </li>
          );
        })}
      </ol>
      {remaining > 0 ? (
        <div className="border-t px-4 py-2">
          <button
            type="button"
            onClick={() => setShown((count) => count + NEXT_PAGE)}
            className="rounded-full px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Show {Math.min(NEXT_PAGE, remaining)} earlier ({remaining} left)
          </button>
        </div>
      ) : null}
    </>
  );
}

function Round({
  trade,
  market,
  initial,
  switchedFrom,
  divided,
}: {
  trade: TradeRound;
  market: Market;
  initial: boolean;
  /** Set on the first round after the ranking source changed. */
  switchedFrom: string | null;
  /** A hairline above, except directly under a group heading. */
  divided: boolean;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[5.5rem_1fr_auto] gap-x-3 px-4 py-3 sm:grid-cols-[7rem_1fr_auto]",
        divided && "border-t",
      )}
    >
      <div>
        <p className="text-sm font-semibold">{formatDate(trade.entrySession)}</p>
        <p className="text-[11px] text-muted-foreground">{initial ? "first purchase" : `ranked ${shortDate(trade.rankDate)}`}</p>
      </div>
      <div className="min-w-0 space-y-1 text-xs">
        {trade.bought.length || trade.sold.length ? (
          <>
            <Names sign="+" symbols={trade.bought} market={market} tone="text-positive" />
            <Names sign="−" symbols={trade.sold} market={market} tone="text-negative" />
          </>
        ) : (
          <p className="text-muted-foreground">No changes; weights reset to equal.</p>
        )}
        {switchedFrom ? (
          <p className="text-[11px] text-caution">
            Switched from {switchedFrom}. The ranking method changed, so more of the basket was replaced than
            usual.
          </p>
        ) : null}
      </div>
      <div className="text-right">
        <ReturnText value={trade.returnPct} size="sm" />
        <p className="tabular text-[11px] whitespace-nowrap text-muted-foreground">
          to {shortDate(trade.periodEnd)}
          {trade.costPct > 0 ? ` · ${trade.costPct.toFixed(2)} pts` : ""}
        </p>
      </div>
    </div>
  );
}

/** "16 Sep", the year only when it is not this row's context. */
function shortDate(value: string) {
  return formatDate(value).replace(/\s\d{4}$/, "");
}

function Names({
  sign,
  symbols,
  market,
  tone,
}: {
  sign: string;
  symbols: string[];
  market: Market;
  tone: string;
}) {
  const [open, setOpen] = useState(false);
  if (!symbols.length) return null;
  const shown = open ? symbols : symbols.slice(0, NAMES_SHOWN);
  const hidden = symbols.length - shown.length;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className={cn("w-3 shrink-0 font-semibold", tone)} aria-label={sign === "+" ? "bought" : "sold"}>
        {sign}
      </span>
      {shown.map((symbol) => (
        <Link
          key={symbol}
          href={marketPath(market.slug, `/stocks/${encodeURIComponent(symbol)}`)}
          prefetch={false}
          className="font-mono underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {symbol}
        </Link>
      ))}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-full px-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          +{hidden} more
        </button>
      ) : null}
    </p>
  );
}

/** Whole calendar days from one ISO date to another. */
function daysBetween(from: string, to: string) {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

function median(values: number[]) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * Every position the basket has sold, like a broker's contract notes: bought
 * on, at; sold on, at; held for; returned. Price to price, so it leaves out
 * the equal-weight trims in between and the trading costs, which the
 * basket-level figures carry.
 *
 * The summary line answers "how often did a pick work, and by how much" --
 * the question a list of hundreds of rows cannot answer at a glance -- and the
 * order switch surfaces the outliers without a sortable-header affordance on
 * every column.
 */
function Closed({ trades, market }: { trades: ClosedTrade[]; market: Market }) {
  const [order, setOrder] = useState<ClosedOrder>("recent");
  const [shown, setShown] = useState(CLOSED_PAGE);
  const returns = trades.map((trade) => trade.returnPct).filter((value): value is number => value !== null);
  const won = returns.filter((value) => value > 0).length;
  const average = returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : null;
  const middle = median(returns);

  const ordered = [...trades].sort((a, b) => {
    if (order === "recent") return a.soldOn < b.soldOn ? 1 : a.soldOn > b.soldOn ? -1 : 0;
    const left = a.returnPct ?? (order === "best" ? -Infinity : Infinity);
    const right = b.returnPct ?? (order === "best" ? -Infinity : Infinity);
    return order === "best" ? right - left : left - right;
  });
  const visible = ordered.slice(0, shown);
  const remaining = ordered.length - visible.length;

  if (!trades.length) {
    return (
      <p className="px-4 py-10 text-center text-sm text-muted-foreground">
        Nothing has been sold yet. A position closes when a rebalance drops it from the top.
      </p>
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-3">
        <p className="text-xs text-muted-foreground">
          {trades.length} closed, {won} of {returns.length} won ({returns.length ? Math.round((won / returns.length) * 100) : 0}
          %). Average {formatPercent(average, 2, true)}, median {formatPercent(middle, 2, true)}. Each return is that
          stock&rsquo;s own, from purchase to sale, before costs.
        </p>
        <SegmentedControl
          label="Order closed positions"
          value={order}
          onChange={(next) => {
            setOrder(next);
            setShown(CLOSED_PAGE);
          }}
          options={[
            { value: "recent", label: "Recent" },
            { value: "best", label: "Best" },
            { value: "worst", label: "Worst" },
          ]}
        />
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm sm:min-w-[640px]">
          <thead>
            <tr className="border-y text-left text-[11px] font-medium text-muted-foreground">
              <th className="px-4 py-2 font-medium">Stock</th>
              <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Bought</th>
              <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Sold</th>
              <th className="px-2 py-2 text-right font-medium">Held</th>
              <th className="px-4 py-2 text-right font-medium">Return</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {visible.map((trade) => (
              <tr key={`${trade.symbol}-${trade.soldOn}`} className="hover:bg-muted/50">
                <td className="max-w-[18rem] px-4 py-2">
                  <Link
                    href={marketPath(market.slug, `/stocks/${encodeURIComponent(trade.symbol)}`)}
                    prefetch={false}
                    className="group flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <CompanyLogo symbol={trade.symbol} domain={trade.logoDomain} />
                    <span className="min-w-0">
                      <span className="block font-mono text-xs font-semibold underline-offset-2 group-hover:underline">
                        {trade.symbol}
                      </span>
                      <span className="block truncate text-[11px] text-muted-foreground sm:hidden">
                        {trade.boughtOn ? shortDate(trade.boughtOn) : MISSING} → {shortDate(trade.soldOn)}
                      </span>
                      <span className="hidden truncate text-[11px] text-muted-foreground sm:block">
                        {trade.company ?? "No longer listed"}
                      </span>
                    </span>
                  </Link>
                </td>
                <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                  {trade.boughtAt !== null ? formatMoney(trade.boughtAt, market, market.listPriceDigits) : MISSING}
                  <span className="block text-[10px] text-muted-foreground">
                    {trade.boughtOn ? formatDate(trade.boughtOn) : "never filled"}
                    {trade.backtest ? <span className="text-caution"> · backtest</span> : null}
                  </span>
                </td>
                <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                  {trade.soldAt !== null ? formatMoney(trade.soldAt, market, market.listPriceDigits) : MISSING}
                  <span className="block text-[10px] text-muted-foreground">{formatDate(trade.soldOn)}</span>
                </td>
                <td className="tabular px-2 py-2 text-right font-mono text-xs text-muted-foreground">
                  {trade.boughtOn ? `${daysBetween(trade.boughtOn, trade.soldOn)}d` : MISSING}
                </td>
                <td className="px-4 py-2 text-right">
                  <ReturnText value={trade.returnPct} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {remaining > 0 ? (
        <div className="border-t px-4 py-2">
          <button
            type="button"
            onClick={() => setShown((count) => count + CLOSED_PAGE * 2)}
            className="rounded-full px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Show {Math.min(CLOSED_PAGE * 2, remaining)} more ({remaining} left)
          </button>
        </div>
      ) : null}
    </>
  );
}
