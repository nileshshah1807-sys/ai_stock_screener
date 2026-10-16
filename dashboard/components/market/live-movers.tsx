"use client";

import { useEffect, useRef, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";

import { RatingBadge } from "@/components/rating-badge";
import { SegmentedControl } from "@/components/segmented-control";
import { StockListRow } from "@/components/stock-identity";
import { TickFlash } from "@/components/tick-flash";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, formatPercent } from "@/lib/format";
import { REFRESH_MS, isLive, nextPollDelay, quoteTime } from "@/lib/live-quotes.mjs";
import {
  LIVE_MOVERS_LIMIT,
  normalizeLiveMarket,
  withTicks,
  type LiveIndexMovers,
  type LiveMarket,
  type LiveMover,
} from "@/lib/live-market";
import type { Market } from "@/lib/markets";
import { createClient } from "@/lib/supabase/client";
import { useNow } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

/**
 * Today's biggest gains and falls within each index, from the five-minute
 * quotes (workers/live_quotes.py).
 *
 * The server renders the movers it read with the rest of the page, so the
 * section is there on first paint; this component then keeps them current,
 * asking once per worker run while the tab is visible. Every index arrives in
 * that one answer, so switching index is local state and costs no request.
 */
export function LiveMovers({ market, initial }: { market: Market; initial: LiveMarket | null }) {
  const data = useLiveMarket(market, initial);
  const [chosen, setChosen] = useState<string | null>(null);
  if (!data) return null;

  const index = data.indices.find((entry) => entry.name === chosen) ?? data.indices[0];

  return (
    <section aria-labelledby="live-movers-title" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div>
          <h2 id="live-movers-title" className="text-lead font-semibold tracking-[-0.011em]">
            Today&rsquo;s movers
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            The biggest gains and falls within each index, refreshed every five minutes during
            the session.
          </p>
        </div>
        <Freshness market={market} data={data} />
      </div>

      <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <SegmentedControl
          label="Index"
          kind="tabs"
          idPrefix="live-movers"
          value={index.name}
          onChange={setChosen}
          options={data.indices.map((entry) => ({ value: entry.name, label: shortName(entry.name) }))}
        />
      </div>

      <div
        role="tabpanel"
        id={`live-movers-panel-${index.name}`}
        aria-labelledby={`live-movers-tab-${index.name}`}
        className="panel overflow-hidden"
      >
        <IndexSummary market={market} index={index} />
        <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <MoverColumn
            market={market}
            title="Top gainers"
            icon={TrendingUp}
            rows={index.gainers}
            empty="No stock in this index is up today."
          />
          <MoverColumn
            market={market}
            title="Top losers"
            icon={TrendingDown}
            rows={index.losers}
            empty="No stock in this index is down today."
          />
        </div>
      </div>
    </section>
  );
}

/**
 * The section's shape while its read streams in, so the breadth charts below
 * do not move when it lands.
 */
export function LiveMoversSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true">
      <div className="space-y-1.5">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-full max-w-md" />
      </div>
      <Skeleton className="h-10 w-full max-w-xl rounded-full" />
      <div className="panel overflow-hidden">
        <div className="border-b px-4 py-3">
          <Skeleton className="h-9 w-56" />
        </div>
        <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          {[0, 1].map((column) => (
            <div key={column} className="pt-3">
              <Skeleton className="mx-4 mb-2 h-3 w-24" />
              {Array.from({ length: LIVE_MOVERS_LIMIT }).map((_, row) => (
                <div key={row} className="px-4 py-2">
                  <Skeleton className="h-[31px] w-full" />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** "Nifty Smallcap 250" -> "Smallcap 250": the tabs sit under one heading. */
function shortName(name: string) {
  const short = name.replace(/^Nifty /, "");
  return /^\d/.test(short) ? name : short;
}

function useLiveMarket(market: Market, initial: LiveMarket | null): LiveMarket | null {
  const [data, setData] = useState(initial);
  // A server render (a breadth group change re-renders the page) can bring
  // newer movers than the last poll; take whichever is newer.
  const [seenInitial, setSeenInitial] = useState(initial);
  if (initial !== seenInitial) {
    setSeenInitial(initial);
    if (initial && (initial.fetched_at ?? "") > (data?.fetched_at ?? "")) setData(initial);
  }
  const fetchedAt = useRef(data?.fetched_at ?? null);
  useEffect(() => {
    fetchedAt.current = data?.fetched_at ?? null;
  }, [data]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(tick, nextPollDelay(fetchedAt.current, Date.now()));
    };
    const tick = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      const { data: fresh, error } = await createClient().rpc("live_market", {
        p_market: market.code,
        p_limit: LIVE_MOVERS_LIMIT,
      });
      if (stopped) return;
      const next = error ? null : normalizeLiveMarket(fresh);
      if (next && next.fetched_at !== fetchedAt.current) {
        fetchedAt.current = next.fetched_at;
        const at = Date.now();
        setData((previous) => withTicks(previous, next, at));
      }
      schedule();
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      // Back on the tab: ask at once if a run has landed since, else wait for it.
      const written = fetchedAt.current ? Date.parse(fetchedAt.current) : NaN;
      if (!Number.isFinite(written) || Date.now() - written > REFRESH_MS) void tick();
      else schedule();
    };

    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [market.code]);

  return data;
}

function Freshness({ market, data }: { market: Market; data: LiveMarket }) {
  const now = useNow();
  const live = isLive(data.fetched_at, now);
  const time = quoteTime(data.traded_at, market.timezone, market.locale, now);
  return (
    // The server and the browser read the clock a moment apart.
    <p suppressHydrationWarning className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {live ? (
        <span className="relative flex size-2" aria-hidden>
          <span className="absolute inline-flex size-full rounded-full bg-positive opacity-60 motion-safe:animate-ping" />
          <span className="relative inline-flex size-2 rounded-full bg-positive" />
        </span>
      ) : null}
      {live ? "Live" : "As of"} {time} {market.timezoneLabel}
    </p>
  );
}

function IndexSummary({ market, index }: { market: Market; index: LiveIndexMovers }) {
  const counted = index.advances + index.declines + index.unchanged;
  const share = (value: number) => (counted ? (value / counted) * 100 : 0);
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-semibold">{index.name}</p>
        {index.level !== null ? (
          <p className="tabular font-mono text-xs">
            <TickFlash tick={index.tick}>
              {index.level.toLocaleString(market.locale, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </TickFlash>{" "}
            <span
              className={cn(
                index.change_pct === null
                  ? "text-muted-foreground"
                  : index.change_pct >= 0
                    ? "text-positive"
                    : "text-negative",
              )}
            >
              {formatPercent(index.change_pct, 2, true)}
            </span>
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{index.members} stocks</p>
        )}
      </div>

      {counted ? (
        <div className="min-w-48 flex-1 sm:max-w-sm">
          <div
            className="flex h-1.5 overflow-hidden rounded-full bg-muted"
            role="img"
            aria-label={`${index.advances} advancing, ${index.declines} declining, ${index.unchanged} unchanged`}
          >
            <span className="bg-positive" style={{ width: `${share(index.advances)}%` }} />
            <span className="ml-auto bg-negative" style={{ width: `${share(index.declines)}%` }} />
          </div>
          <p className="tabular mt-1 flex justify-between font-mono text-[11px] text-muted-foreground">
            <span>
              <span className="text-positive">{index.advances}</span> advancing
            </span>
            <span>
              <span className="text-negative">{index.declines}</span> declining
            </span>
          </p>
        </div>
      ) : null}
    </div>
  );
}

function MoverColumn({
  market,
  title,
  icon: Icon,
  rows,
  empty,
}: {
  market: Market;
  title: string;
  icon: typeof TrendingUp;
  rows: LiveMover[];
  empty: string;
}) {
  return (
    <div className="min-w-0">
      <h3 className="flex items-center gap-2 px-4 pb-1 pt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="size-3.5" aria-hidden />
        {title}
      </h3>
      {rows.length ? (
        <ul className="divide-y">
          {rows.map((row) => (
            <li key={row.symbol}>
              <MoverRow market={market} row={row} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}

function MoverRow({ market, row }: { market: Market; row: LiveMover }) {
  return (
    <StockListRow
      symbol={row.symbol}
      company={row.company}
      rank={row.investment_rank}
      // An index member the screener does not rate has no stock page to open.
      linked={row.investment_rank !== null}
    >
      <TickFlash
        tick={row.tick}
        className="tabular hidden font-mono text-[11px] text-muted-foreground sm:inline"
      >
        {formatMoney(row.price, market, market.listPriceDigits)}
      </TickFlash>
      <span
        className={cn(
          "tabular w-16 shrink-0 text-right font-mono text-xs",
          row.change_pct >= 0 ? "text-positive" : "text-negative",
        )}
      >
        {formatPercent(row.change_pct, 2, true)}
      </span>
      <span className="hidden w-20 shrink-0 justify-end sm:flex">
        {row.rating ? <RatingBadge rating={row.rating} /> : null}
      </span>
    </StockListRow>
  );
}
