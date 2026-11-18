"use client";

import { useEffect, useState } from "react";

import { useLiveFromR2 } from "@/components/market-provider";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatInteger, formatNumber } from "@/lib/format";
import { flowSummary, indexFuturesPositioning } from "@/lib/market-flows.mjs";
import { importFailed, lazyClient, liveApi } from "@/lib/supabase/lazy-client";
import { cn } from "@/lib/utils";

type FlowSession = { date: string; fii: number | null; dii: number | null };
type FlowWindow = { sessions: number; fii: number | null; dii: number | null };
type Flows = { date: string; bars: FlowSession[]; fiveDay: FlowWindow; monthToDate: FlowWindow };
type Participant = { category: string; long: number; short: number; net: number; longShare: number | null };
type Positioning = { date: string; participants: Participant[] };
type Data = { flows: Flows | null; positioning: Positioning | null };

/** Enough sessions for 20 bars and any month to date, two rows a session. */
const FLOW_ROWS = 50;

/**
 * NSE's institutional flows on the Market page: FII and DII net cash buying per
 * session, and index-futures open positions by participant
 * (workers/market_flows.py). Read once in the browser after render, from the R2
 * objects through /api/live or from the tables, so the page's server render does
 * no work for it. Daily data: no polling.
 */
export function MarketFlows() {
  const fromR2 = useLiveFromR2();
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    void read(fromR2).then((answer) => {
      if (stopped) return;
      if (answer) setData(answer);
      else setFailed(true);
    });
    return () => {
      stopped = true;
    };
  }, [fromR2]);

  return (
    <section aria-labelledby="market-flows-title" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 id="market-flows-title" className="text-lead font-semibold tracking-[-0.011em]">
          FII and DII flows
        </h2>
        {data?.flows ? <p className="text-xs text-muted-foreground">Cash market, as of {formatDate(data.flows.date)}</p> : null}
      </div>
      {data ? (
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
          <FlowsPanel flows={data.flows} />
          <PositioningPanel positioning={data.positioning} />
        </div>
      ) : failed ? (
        <div className="panel px-5 py-8 text-center text-sm text-muted-foreground">Couldn&rsquo;t load institutional flows.</div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}
    </section>
  );
}

async function read(fromR2: boolean): Promise<Data | null> {
  if (fromR2) {
    const { data, error } = await liveApi({ market: "NSE", kind: "flows" });
    return error ? null : (data as Data);
  }
  const answers = await lazyClient()
    .then((client) =>
      Promise.all([
        client.from("fii_dii_flows").select("session_date,category,net_value").eq("market", "NSE").order("session_date", { ascending: false }).limit(FLOW_ROWS),
        // Four participants a session: the newest four rows are the latest session.
        client.from("participant_oi").select("session_date,category,future_index_long,future_index_short").eq("market", "NSE").order("session_date", { ascending: false }).limit(4),
      ]),
    )
    .catch((error) => [importFailed(error), importFailed(error)] as const);
  const [flows, oi] = answers;
  if (flows.error || oi.error) return null;
  return { flows: flowSummary(flows.data), positioning: indexFuturesPositioning(oi.data) };
}

const crore = (value: number | null) =>
  value === null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}₹${formatNumber(Math.abs(value), 0)} cr`;
const tone = (value: number | null) => (value === null || value === 0 ? "" : value > 0 ? "text-positive" : "text-negative");

function FlowsPanel({ flows }: { flows: Flows | null }) {
  if (!flows) {
    return (
      <div className="panel px-5 py-8 text-sm text-muted-foreground">
        No cash-flow sessions recorded yet. The history starts with the first session the daily job stores.
      </div>
    );
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
        Net buying (buys less sells) in the cash market, in rupees crore, as NSE reports it. Both rows share one scale.
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

function PositioningPanel({ positioning }: { positioning: Positioning | null }) {
  return (
    <div className="panel p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold">Index futures positions</h3>
        {positioning ? <p className="text-xs text-muted-foreground">Open contracts, {formatDate(positioning.date)}</p> : null}
      </div>
      {positioning?.participants.length ? (
        <table className="mt-3 w-full text-sm tabular-nums">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="py-1.5 text-left font-normal">Participant</th>
              <th scope="col" className="py-1.5 text-right font-normal">Long</th>
              <th scope="col" className="py-1.5 text-right font-normal">Short</th>
              <th scope="col" className="py-1.5 text-right font-normal">Net</th>
            </tr>
          </thead>
          <tbody>
            {positioning.participants.map((p) => (
              <tr key={p.category} className="border-t">
                <th scope="row" className="py-2.5 text-left font-medium">
                  {p.category}
                  <LongShare share={p.longShare} />
                </th>
                <td className="py-2.5 text-right">{formatInteger(p.long)}</td>
                <td className="py-2.5 text-right">{formatInteger(p.short)}</td>
                <td className={cn("py-2.5 text-right font-medium", tone(p.net))}>
                  {p.net > 0 ? "+" : p.net < 0 ? "−" : ""}
                  {formatInteger(Math.abs(p.net))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">No positions recorded yet.</p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">From NSE&rsquo;s participant-wise open interest. The bar is each participant&rsquo;s long share.</p>
    </div>
  );
}

/** The long share of a participant's open index-futures contracts, as a split bar. */
function LongShare({ share }: { share: number | null }) {
  if (share === null) return null;
  const percent = Math.round(share * 100);
  return (
    <span className="mt-1 flex items-center gap-2 text-micro font-normal text-muted-foreground">
      <span aria-hidden className="flex h-1.5 w-20 overflow-hidden rounded-full bg-negative/60">
        <span className="bg-positive" style={{ width: `${percent}%` }} />
      </span>
      {percent}% long
    </span>
  );
}
