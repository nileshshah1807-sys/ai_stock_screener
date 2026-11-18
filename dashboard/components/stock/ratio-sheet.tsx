"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { LiveRatio, type RatioFormat } from "@/components/live-quote";
import { useMarket } from "@/components/market-provider";
import { PanelSheet } from "@/components/panel-sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatInteger, formatMoney, formatMoneyCompact, formatNumber, formatPercent } from "@/lib/format";
import { ratioOverlay } from "@/lib/live-quotes.mjs";
import { RATIO_SHEETS, basisSource, peerComparison, ratioHistory, ratioInputs } from "@/lib/ratio-sheet.mjs";
import { liveApi } from "@/lib/supabase/lazy-client";
import { useLiveQuotes, type LiveRatioKey } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

type Sheet = {
  basis?: Record<string, unknown> & { filing_url?: string | null; quarters?: string[] };
  history?: Record<string, unknown>[];
  peers?: { industry: string | null; rows: Record<string, unknown>[] };
} | null;
type Market = ReturnType<typeof useMarket>;

/**
 * A price-ratio tile's value as a button: tapping it opens the ratio taken apart
 * (inputs at the live price, its own quarter-end history and median, its
 * industry peers, the filing it rests on). The sheet's object is read only when
 * it opens, from R2 through /api/live; the page's server render does nothing more.
 */
export function RatioSheet({
  symbol,
  barDate,
  metric,
  format,
  close,
  closePrice,
}: {
  symbol: string;
  barDate: string | null;
  metric: LiveRatioKey;
  format: RatioFormat;
  close: number | null;
  closePrice: number | null;
}) {
  const market = useMarket();
  const [open, setOpen] = useState(false);
  const [sheet, setSheet] = useState<Sheet | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const name = RATIO_SHEETS[metric].name;

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next || sheet !== undefined) return;
    setFailed(false);
    void liveApi({ market: market.code, kind: "ratio", s: symbol }).then(({ data, error }) => {
      if (error) setFailed(true);
      else setSheet((data as Sheet) ?? null);
    });
  };

  return (
    <>
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className="cursor-pointer rounded-sm underline decoration-dotted decoration-muted-foreground/60 underline-offset-4 hover:decoration-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`${name}: see how it is worked out`}
      >
        <LiveRatio symbol={symbol} barDate={barDate} metric={metric} close={close} format={format} />
      </button>
      <PanelSheet
        open={open}
        onOpenChange={onOpenChange}
        title={`${name}, ${symbol}`}
        description="How the figure is worked out, against its own history and its industry."
        note="Reported figures only. Not advice."
        actions={
          <Button type="button" variant="ghost" className="h-11 px-4" onClick={() => setOpen(false)}>
            Close
          </Button>
        }
      >
        {open ? (
          <SheetBody symbol={symbol} barDate={barDate} metric={metric} format={format} close={close} closePrice={closePrice} sheet={sheet} failed={failed} market={market} />
        ) : null}
      </PanelSheet>
    </>
  );
}

function SheetBody({
  symbol,
  barDate,
  metric,
  format,
  close,
  closePrice,
  sheet,
  failed,
  market,
}: {
  symbol: string;
  barDate: string | null;
  metric: LiveRatioKey;
  format: RatioFormat;
  close: number | null;
  closePrice: number | null;
  sheet: Sheet | undefined;
  failed: boolean;
  market: Market;
}) {
  const quote = ratioOverlay(useLiveQuotes(market.code, [symbol])(symbol), barDate);
  if (failed) return <p className="py-6 text-sm text-muted-foreground">Couldn&rsquo;t load this sheet. Close and try again.</p>;
  if (sheet === undefined) return <Skeleton className="my-5 h-72 rounded-xl" />;

  // The live price when a quote is newer than the close, else the close (a close has no withheld change).
  const price = quote ? quote.price : closePrice;
  const inputs = ratioInputs(metric, price, quote ? quote.change_pct : 0, sheet?.basis);
  
  const peers = peerComparison(sheet?.peers, metric);
  const show = (value: number | null) => formatValue(value, format === "money" ? "money" : format === "number2" ? "multiple2" : "multiple", market);
  // With no published inputs, the tile's own figure (live, else the run's close).
  const current = inputs.value ?? quote?.[metric] ?? close;
  const history = ratioHistory(sheet?.history, metric, current);

  return (
    <div className="space-y-6 pt-4 pb-6">
      <section aria-label="Current figure">
        <p className="text-display font-semibold tabular-nums">{show(current)}</p>
        <p className="mt-1 text-xs text-muted-foreground">{quote ? "At the latest price." : "At the last close."}</p>
      </section>

      <section aria-labelledby="ratio-inputs" className="space-y-2">
        <h3 id="ratio-inputs" className="text-sm font-semibold">Inputs</h3>
        {sheet?.basis ? (
          <>
            <dl className="divide-y rounded-row border text-sm">
              {inputs.steps.map((step) => (
                <div key={step.label} className="flex justify-between gap-4 px-3 py-2">
                  <dt className="text-muted-foreground">{step.label}</dt>
                  <dd className="font-medium tabular-nums">{formatValue(step.value, step.unit, market)}</dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-muted-foreground">
              {basisSource(sheet.basis)}.{" "}
              {sheet.basis.filing_url ? (
                <a href={sheet.basis.filing_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground">
                  Source filing <ExternalLink className="size-3" aria-hidden />
                </a>
              ) : null}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">The inputs for this stock are not published yet.</p>
        )}
      </section>

      {history.points.some((p: { value: number | null }) => p.value !== null) ? (
        <section aria-labelledby="ratio-history" className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h3 id="ratio-history" className="text-sm font-semibold">At each quarter end</h3>
            <p className="text-xs text-muted-foreground tabular-nums">Median {show(history.median)}</p>
          </div>
          <HistoryBars points={history.points} median={history.median} show={show} />
          {history.vsMedian !== null ? (
            <p className="text-xs text-muted-foreground">
              Now {formatPercent(Math.abs(history.vsMedian) * 100, 0)} {history.vsMedian >= 0 ? "above" : "below"} its median over these {history.points.length} quarters.
            </p>
          ) : null}
        </section>
      ) : null}

      {peers.rows.length ? (
        <section aria-labelledby="ratio-peers" className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h3 id="ratio-peers" className="text-sm font-semibold">Industry peers</h3>
            {peers.industry ? <p className="truncate text-xs text-muted-foreground">{peers.industry}</p> : null}
          </div>
          <table className="w-full text-sm tabular-nums">
            <tbody>
              <tr className="font-medium">
                <th scope="row" className="py-1.5 text-left">{symbol}</th>
                <td className="py-1.5 text-right">{show(current)}</td>
              </tr>
              {peers.rows.map((row) => (
                <tr key={row.symbol} className="border-t">
                  <th scope="row" className="py-1.5 text-left font-normal">
                    <span className="block truncate">{row.company}</span>
                  </th>
                  <td className="py-1.5 text-right">{show(row.value)}</td>
                </tr>
              ))}
              <tr className="border-t text-muted-foreground">
                <th scope="row" className="py-1.5 text-left font-normal">Peer median</th>
                <td className="py-1.5 text-right">{show(peers.median)}</td>
              </tr>
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">Peers at the last close; this stock at the price above.</p>
        </section>
      ) : null}
    </div>
  );
}

/** Quarter-end values as bars, with the median as a dashed line across them. */
function HistoryBars({ points, median, show }: { points: { period_end: string; value: number | null }[]; median: number | null; show: (v: number | null) => string }) {
  const top = Math.max(...points.map((p) => p.value ?? 0), median ?? 0) || 1;
  return (
    <figure>
      <div role="img" aria-label={`Quarter-end values from ${points[0]?.period_end} to ${points.at(-1)?.period_end}, median ${show(median)}`} className="relative flex h-28 items-end gap-1">
        {points.map((p) => (
          <div key={p.period_end} title={`${p.period_end}: ${show(p.value)}`} className="flex h-full flex-1 items-end">
            <span className={cn("w-full rounded-t-[2px]", p.value !== null && p.value > 0 ? "bg-chart-2/80" : "")} style={{ height: `${p.value !== null && p.value > 0 ? (p.value / top) * 100 : 0}%` }} />
          </div>
        ))}
        {median !== null && median > 0 ? (
          <span aria-hidden className="absolute inset-x-0 border-t border-dashed border-foreground/60" style={{ bottom: `${(median / top) * 100}%` }} />
        ) : null}
      </div>
      <div className="mt-1 flex justify-between text-micro text-muted-foreground tabular-nums">
        <span>{points[0]?.period_end}</span>
        <span>{points.at(-1)?.period_end}</span>
      </div>
    </figure>
  );
}

function formatValue(value: number | null, unit: string, market: Market): string {
  if (unit === "money") return formatMoneyCompact(value, market);
  if (unit === "price") return formatMoney(value, market);
  if (unit === "count") return formatInteger(value);
  return value === null ? "—" : `${formatNumber(value, unit === "multiple2" ? 2 : 1)}×`;
}
