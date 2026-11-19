import { FlowBars } from "@/components/market/flow-bars";
import { FLOW_INK, FLOW_LABEL, flowFormat, type FlowCategory, type FlowSession } from "@/components/market/flow-format";
import { CATEGORIES, flowSessions, netOver } from "@/lib/fii-dii.mjs";
import { formatDate } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

/** Sessions drawn, and the running total's span. */
const SHOWN = 60;
const RUN = 20;

/**
 * Who bought and sold the cash market: NSE's provisional FII/FPI and DII
 * figures for each session (workers/market_flows.py), the latest in a table
 * and every session as paired daily bars (FlowBars, the one client piece,
 * for its hover readout). NSE keeps no archive, so the history begins the
 * day the worker was switched on, and the chart says so rather than
 * implying a longer record.
 */
export function FiiDiiFlows({ market, rows }: { market: Market; rows: Record<string, unknown>[] }) {
  const sessions = flowSessions(rows) as FlowSession[];
  const latest = sessions.at(-1);
  if (!latest) return null;

  const { money, signed, tone } = flowFormat(market);
  const run = Math.min(RUN, sessions.length);

  return (
    <section aria-labelledby="flows-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="flows-title" className="text-lead font-semibold tracking-[-0.011em]">
          FII / DII cash flows
        </h2>
        <p className="text-xs text-muted-foreground">NSE provisional figures for {formatDate(latest.session)}</p>
      </div>

      <div className="panel grid gap-x-8 gap-y-5 p-4 sm:p-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[22rem] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="pb-2 text-left font-medium">
                  <span className="sr-only">Investor</span>
                </th>
                <th scope="col" className="pb-2 text-right font-medium">Net</th>
                <th scope="col" className="pb-2 text-right font-medium">Bought</th>
                <th scope="col" className="pb-2 text-right font-medium">Sold</th>
                <th scope="col" className="pb-2 text-right font-medium" title={`Sum of the last ${run} sessions' net`}>
                  {run === 1 ? "1 session" : `${run} sessions`}
                </th>
              </tr>
            </thead>
            <tbody className="tabular font-mono text-xs">
              {(CATEGORIES as FlowCategory[]).map((key) => {
                const today = latest[key];
                const total = netOver(sessions, key, run);
                return (
                  <tr key={key} className="border-t border-border/60">
                    <th scope="row" className="py-2.5 text-left font-sans text-sm font-medium">
                      <span className="inline-flex items-center gap-2">
                        <span className="size-2 rounded-[2px]" style={{ background: FLOW_INK[key] }} aria-hidden />
                        {FLOW_LABEL[key]}
                      </span>
                    </th>
                    <td className={cn("py-2.5 text-right text-sm font-semibold", tone(today?.net))}>{signed(today?.net)}</td>
                    <td className="py-2.5 text-right text-muted-foreground">{money(today?.buy)}</td>
                    <td className="py-2.5 text-right text-muted-foreground">{money(today?.sell)}</td>
                    <td className={cn("py-2.5 text-right", tone(total.net))}>{signed(total.net)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <FlowBars market={market} sessions={sessions.slice(-SHOWN)} />
      </div>
    </section>
  );
}
