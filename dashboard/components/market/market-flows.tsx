"use client";

import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatNumber } from "@/lib/format";
import { liveApi } from "@/lib/supabase/lazy-client";
import { cn } from "@/lib/utils";

type FlowSession = { date: string; fii: number | null; dii: number | null };
type FlowWindow = { sessions: number; fii: number | null; dii: number | null };
type Flows = { date: string; bars: FlowSession[]; fiveDay: FlowWindow; monthToDate: FlowWindow };
type FlowYear = { year: number; fii: number | null; dii: number | null; sessions: number };
type Data = { flows: Flows | null; years: FlowYear[] | null };

/**
 * NSE's institutional cash flows on the Market page: FII and DII net buying per
 * session and per calendar year (workers/market_flows.py). Read once in the
 * browser after render from the R2 object through /api/live, so the page's
 * server render does no work for it. Daily data: no polling.
 */
export function MarketFlows() {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    void liveApi({ market: "NSE", kind: "flows" }).then(({ data: answer, error }) => {
      if (stopped) return;
      if (error || !answer) setFailed(true);
      else setData(answer as Data);
    });
    return () => {
      stopped = true;
    };
  }, []);

  return (
    <section aria-labelledby="market-flows-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="market-flows-title" className="text-lead font-semibold tracking-[-0.011em]">
          FII and DII flows
        </h2>
        {data?.flows ? <p className="text-xs text-muted-foreground">Cash market, as of {formatDate(data.flows.date)}</p> : null}
      </div>
      {data ? (
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
          <FlowsPanel flows={data.flows} />
          <YearsPanel years={data.years} latest={data.flows?.date ?? null} />
        </div>
      ) : failed ? (
        <div className="panel px-5 py-8 text-center text-sm text-muted-foreground">Couldn&rsquo;t load institutional flows. Reload the page to try again.</div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]" aria-busy>
          <Skeleton className="h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      )}
    </section>
  );
}

const crore = (value: number | null) =>
  value === null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}₹${formatNumber(Math.abs(value), 0)} cr`;
const tone = (value: number | null) => (value === null || value === 0 ? "" : value > 0 ? "text-positive" : "text-negative");

function FlowsPanel({ flows }: { flows: Flows | null }) {
  if (!flows) {
    return <div className="panel px-5 py-8 text-sm text-muted-foreground">No sessions published yet. The next evening run adds them.</div>;
  }
  const largest = Math.max(1, ...flows.bars.flatMap((s) => [Math.abs(s.fii ?? 0), Math.abs(s.dii ?? 0)]));
  return (
    <div className="panel space-y-5 p-4 sm:p-5">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Total label={`FII, last ${flows.fiveDay.sessions} sessions`} value={flows.fiveDay.fii} />
        <Total label={`DII, last ${flows.fiveDay.sessions} sessions`} value={flows.fiveDay.dii} />
        <Total label="FII, month to date" value={flows.monthToDate.fii} />
        <Total label="DII, month to date" value={flows.monthToDate.dii} />
      </dl>
      <Bars label="FII net per session" bars={flows.bars} side="fii" largest={largest} />
      <Bars label="DII net per session" bars={flows.bars} side="dii" largest={largest} />
      <p className="text-xs text-muted-foreground">
        Net buying (buys less sells) in the cash market, in rupees crore. Both rows share one scale.
      </p>
    </div>
  );
}

function Total({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-row bg-(--control) px-3 py-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("mt-0.5 text-sm font-semibold tabular-nums", tone(value))}>{crore(value)}</dd>
    </div>
  );
}

/** One side's sessions as bars above (net buying) or below (net selling) a zero line. */
function Bars({ label, bars, side, largest }: { label: string; bars: FlowSession[]; side: "fii" | "dii"; largest: number }) {
  return (
    <figure>
      <figcaption className="mb-1.5 text-xs font-medium">{label}</figcaption>
      <div role="img" aria-label={`${label}, ${bars.length} sessions to ${formatDate(bars.at(-1)?.date)}`} className="relative flex h-24 items-stretch gap-[3px]">
        <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-border" />
        {bars.map((session) => {
          const value = session[side];
          const height = value === null ? 0 : (Math.abs(value) / largest) * 50;
          return (
            <div key={session.date} title={`${formatDate(session.date)}: ${crore(value)}`} className="relative flex-1">
              <span
                className={cn("absolute inset-x-0 rounded-[2px]", value !== null && value < 0 ? "top-1/2 bg-negative/80" : "bottom-1/2 bg-positive/80")}
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-micro text-muted-foreground tabular-nums">
        <span>{formatDate(bars[0]?.date)}</span>
        <span>{formatDate(bars.at(-1)?.date)}</span>
      </div>
    </figure>
  );
}

/**
 * Net per calendar year, FII and DII on one scale, each with a bar out from a
 * centre line. On a wide screen it takes the session panel's height and scrolls.
 */
function YearsPanel({ years, latest }: { years: FlowYear[] | null; latest: string | null }) {
  if (!years) {
    return <div className="panel px-5 py-8 text-sm text-muted-foreground">Yearly totals appear with the next evening run.</div>;
  }
  const largest = Math.max(1, ...years.flatMap((y) => [Math.abs(y.fii ?? 0), Math.abs(y.dii ?? 0)]));
  const currentYear = latest ? Number(latest.slice(0, 4)) : null;
  return (
    <div className="panel flex flex-col p-4 sm:p-5 lg:h-0 lg:min-h-full">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold">Year by year</h3>
        <p className="text-xs text-muted-foreground">
          Net, rupees crore, {years.at(-1)?.year} to {years[0].year}
        </p>
      </div>
      <div
        tabIndex={0}
        role="region"
        aria-label="FII and DII net by year"
        className="mt-3 min-h-0 flex-1 overflow-y-auto overscroll-contain rounded-row outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <table className="w-full text-sm tabular-nums">
          <thead className="sticky top-0 z-10 bg-(--card)">
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="w-16 py-1.5 pr-3 text-left font-normal">Year</th>
              <th scope="col" className="py-1.5 pl-3 text-right font-normal">FII</th>
              <th scope="col" className="py-1.5 pl-3 text-right font-normal">DII</th>
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y.year} className="border-t">
                <th scope="row" className="py-2 pr-3 text-left align-top font-medium">
                  {y.year}
                  {y.year === currentYear ? <span className="block text-micro font-normal text-muted-foreground">to date</span> : null}
                </th>
                <NetCell value={y.fii} largest={largest} />
                <NetCell value={y.dii} largest={largest} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** A year's net with a bar from the centre: right for net buying, left for net selling. */
function NetCell({ value, largest }: { value: number | null; largest: number }) {
  const width = value === null ? 0 : (Math.abs(value) / largest) * 50;
  return (
    <td className="py-2 pl-3 text-right align-top">
      <span className={cn("font-medium", tone(value))}>{crore(value)}</span>
      <span aria-hidden className="relative mt-1.5 block h-1 rounded-full bg-(--control)">
        <span className="absolute inset-y-[-2px] left-1/2 w-px bg-border" />
        <span
          className={cn("absolute inset-y-0 rounded-full", value !== null && value < 0 ? "right-1/2 bg-negative/80" : "left-1/2 bg-positive/80")}
          style={{ width: `${width}%` }}
        />
      </span>
    </td>
  );
}
