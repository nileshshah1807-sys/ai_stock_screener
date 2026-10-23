"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Loader2, TrendingDown, TrendingUp } from "lucide-react";

import { Expand } from "@/components/motion";
import { RatingBadge } from "@/components/rating-badge";
import { ScrollFade } from "@/components/scroll-fade";
import { SegmentedControl } from "@/components/segmented-control";
import { StockListRow } from "@/components/stock-identity";
import { TickFlash } from "@/components/tick-flash";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, formatPercent } from "@/lib/format";
import { REFRESH_MS, nextPollDelay, quoteFreshness } from "@/lib/live-quotes.mjs";
import {
  LIVE_MOVERS_LIMIT,
  normalizeLiveMarket,
  withTicks,
  type LiveIndexMovers,
  type LiveMarket,
  type LiveMover,
} from "@/lib/live-market";
import { indexSlug } from "@/lib/indices.mjs";
import { marketPath, type Market } from "@/lib/markets";
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
/**
 * Movers per column once the list is expanded. The first LIVE_MOVERS_LIMIT
 * arrive with the page; the rest are asked for on the press, once, and kept
 * current by the same poll while the list stays open.
 */
const EXPANDED_LIMIT = 25;

type Side = "gainers" | "losers";

export function LiveMovers({
  market,
  initial,
  failed = false,
}: {
  market: Market;
  initial: LiveMarket | null;
  /** The server's read failed, as opposed to finding no quotes. */
  failed?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data, limit } = useLiveMarket(market, initial, expanded ? EXPANDED_LIMIT : LIVE_MOVERS_LIMIT);
  const [chosen, setChosen] = useState<string | null>(null);
  // Below lg the columns stack; one at a time, picked here, keeps the
  // section to a screen rather than twenty rows.
  const [side, setSide] = useState<Side>("gainers");

  // The poll keeps trying, so either message clears itself when a read lands.
  if (!data) {
    return (
      <section aria-labelledby="live-movers-title" className="space-y-3">
        <MoversHeading />
        <div className="panel px-5 py-8 text-center text-sm text-muted-foreground">
          {failed ? "Couldn\u2019t load live prices. Retrying." : "No live prices yet today."}
        </div>
      </section>
    );
  }

  const index = data.indices.find((entry) => entry.name === chosen) ?? data.indices[0];
  // Open only once the longer list is here, so the rows grow in with their
  // content rather than opening on an empty box.
  const showMore = expanded && limit >= EXPANDED_LIMIT;
  const loadingMore = expanded && !showMore;
  const longest = Math.max(index.gainers.length, index.losers.length);

  return (
    <section aria-labelledby="live-movers-title" className="space-y-3">
      <MoversHeading>
        <Freshness market={market} data={data} />
      </MoversHeading>

      <ScrollFade>
        <SegmentedControl
          label="Index"
          kind="tabs"
          idPrefix="live-movers"
          value={index.name}
          onChange={setChosen}
          options={data.indices.map((entry) => ({ value: entry.name, label: shortName(entry.name) }))}
        />
      </ScrollFade>

      <div
        role="tabpanel"
        id={`live-movers-panel-${index.name}`}
        aria-labelledby={`live-movers-tab-${index.name}`}
        className="panel overflow-hidden"
      >
        <IndexSummary market={market} index={index} />
        <div className="border-b px-4 py-2.5 lg:hidden">
          <SegmentedControl<Side>
            label="Show"
            value={side}
            onChange={setSide}
            options={[
              { value: "gainers", label: "Top gainers" },
              { value: "losers", label: "Top losers" },
            ]}
          />
        </div>
        <div className="grid lg:grid-cols-2 lg:divide-x">
          <MoverColumn
            market={market}
            title="Top gainers"
            icon={TrendingUp}
            rows={index.gainers}
            more={showMore}
            empty="No stock in this index is up today."
            className={side === "gainers" ? undefined : "max-lg:hidden"}
          />
          <MoverColumn
            market={market}
            title="Top losers"
            icon={TrendingDown}
            rows={index.losers}
            more={showMore}
            empty="No stock in this index is down today."
            className={side === "losers" ? undefined : "max-lg:hidden"}
          />
        </div>
        {/* The expand bar. Offered while there may be more to show: a full
            first page in either column means the index has more movers. */}
        {expanded || longest >= LIVE_MOVERS_LIMIT ? (
          <button
            type="button"
            onClick={() => setExpanded((open) => !open)}
            aria-expanded={showMore}
            className={cn(
              "flex w-full items-center justify-center gap-1.5 border-t px-4 py-2.5 text-xs font-medium text-muted-foreground",
              "transition-[background-color,color] duration-(--duration-fast) ease-(--ease-standard)",
              "hover:bg-(--control) hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            )}
          >
            {loadingMore ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <ChevronDown
                className={cn(
                  "size-3.5 transition-transform duration-(--duration-slow) ease-(--ease-standard)",
                  showMore && "rotate-180",
                )}
                aria-hidden
              />
            )}
            {showMore ? "Show fewer" : `Show top ${EXPANDED_LIMIT}`}
          </button>
        ) : null}
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
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-8 w-full max-w-xl rounded-lg" />
      <div className="panel overflow-hidden">
        <div className="border-b px-4 py-3">
          <Skeleton className="h-9 w-56" />
        </div>
        <div className="border-b px-4 py-2.5 lg:hidden">
          <Skeleton className="h-8 w-52 rounded-lg" />
        </div>
        <div className="grid lg:grid-cols-2 lg:divide-x">
          {[0, 1].map((column) => (
            <div key={column} className={cn("pt-3", column === 1 && "max-lg:hidden")}>
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

/** The section's heading, with the quotes' freshness beside it once there are any. */
function MoversHeading({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <h2 id="live-movers-title" className="text-lead font-semibold tracking-[-0.011em]">
        Today&rsquo;s movers
      </h2>
      {children}
    </div>
  );
}

/** "Nifty Smallcap 250" -> "Smallcap 250": the tabs sit under one heading. */
function shortName(name: string) {
  const short = name.replace(/^Nifty /, "");
  return /^\d/.test(short) ? name : short;
}

/**
 * The movers, polled once per worker run while the tab is visible, at
 * `limit` per column. Raising `limit` asks at once; `limit` in the answer is
 * how many per column the data now holds.
 */
function useLiveMarket(
  market: Market,
  initial: LiveMarket | null,
  limit: number,
): { data: LiveMarket | null; limit: number } {
  const [data, setData] = useState(initial);
  const [loaded, setLoaded] = useState(LIVE_MOVERS_LIMIT);
  const loadedRef = useRef(LIVE_MOVERS_LIMIT);
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
        p_limit: limit,
      });
      if (stopped) return;
      const next = error ? null : normalizeLiveMarket(fresh);
      // A longer list is news even from the same worker run.
      if (next && (next.fetched_at !== fetchedAt.current || loadedRef.current !== limit)) {
        fetchedAt.current = next.fetched_at;
        loadedRef.current = limit;
        const at = Date.now();
        setData((previous) => withTicks(previous, next, at));
        setLoaded(limit);
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

    // A longer list than the one held is wanted now, not at the next run.
    if (limit > loadedRef.current) void tick();
    else schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [market.code, limit]);

  return { data, limit: loaded };
}

function Freshness({ market, data }: { market: Market; data: LiveMarket }) {
  const now = useNow();
  const { state, label } = quoteFreshness(data.fetched_at, data.traded_at, market, now);
  return (
    // The server and the browser read the clock a moment apart.
    <p suppressHydrationWarning className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {state === "live" ? (
        <span className="relative flex size-2" aria-hidden>
          <span className="absolute inline-flex size-full rounded-full bg-positive opacity-60 motion-safe:animate-ping" />
          <span className="relative inline-flex size-2 rounded-full bg-positive" />
        </span>
      ) : (
        <span
          className={cn(
            "size-2 rounded-full border",
            state === "delayed" ? "border-muted-foreground" : "border-border",
          )}
          aria-hidden
        />
      )}
      {label}
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
            </span>{" "}
            {/* The index cards below show the change over the chosen range;
                this one is the session's, and says so. */}
            <span className="font-sans text-muted-foreground">today</span>
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
          <p className="tabular mt-1 flex justify-between font-mono text-xs text-muted-foreground">
            <span>
              <span className="text-positive">{index.advances}</span> advancing
            </span>
            <span>
              <span className="text-negative">{index.declines}</span> declining
            </span>
          </p>
        </div>
      ) : null}

      <Link
        href={marketPath(market.slug, `/indices/${indexSlug(index.name)}`)}
        className={cn(
          "touch-target inline-flex h-7 shrink-0 items-center gap-0.5 rounded-md bg-(--control) pr-1.5 pl-2.5 text-xs font-medium text-muted-foreground sm:ml-auto",
          "transition-[background-color,color] duration-(--duration-fast) ease-(--ease-standard)",
          "hover:bg-(--control-hover) hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        All {index.members} constituents
        <ChevronRight className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}

function MoverColumn({
  market,
  title,
  icon: Icon,
  rows,
  more,
  empty,
  className,
}: {
  market: Market;
  title: string;
  icon: typeof TrendingUp;
  rows: LiveMover[];
  /** Show the rows past the first page, grown open under it. */
  more: boolean;
  empty: string;
  className?: string;
}) {
  const first = rows.slice(0, LIVE_MOVERS_LIMIT);
  const rest = rows.slice(LIVE_MOVERS_LIMIT);
  return (
    <div className={cn("min-w-0", className)}>
      {/* Below lg the toggle above names the column, so the heading is
          left to screen readers there. */}
      <h3 className="flex items-center gap-2 px-4 pb-1 pt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground max-lg:sr-only">
        <Icon className="size-3.5" aria-hidden />
        {title}
      </h3>
      {rows.length ? (
        <>
          <ul className="divide-y">
            {first.map((row) => (
              <li key={row.symbol}>
                <MoverRow market={market} row={row} />
              </li>
            ))}
          </ul>
          <Expand open={more && rest.length > 0}>
            <ul className="divide-y border-t">
              {rest.map((row) => (
                <li key={row.symbol}>
                  <MoverRow market={market} row={row} />
                </li>
              ))}
            </ul>
          </Expand>
        </>
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
        className="tabular hidden font-mono text-xs text-muted-foreground sm:inline"
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
      {/* The rating stays on a phone: it is the screener's verdict, and the
          reason a mover is worth opening. */}
      <span className="flex w-[4.5rem] shrink-0 justify-end sm:w-20">
        {row.rating ? <RatingBadge rating={row.rating} /> : null}
      </span>
    </StockListRow>
  );
}
