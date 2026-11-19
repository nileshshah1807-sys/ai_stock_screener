"use client";

import { useId, useState } from "react";
import { Minus, Plus } from "lucide-react";

import { useMarket } from "@/components/market-provider";
import { formatMoney } from "@/lib/format";
import { allotmentOdds } from "@/lib/ipos.mjs";

const MAX_APPLICATIONS = 10;

/**
 * Odds of a retail allotment: one minimum lot per applicant by lottery once the
 * retail book is oversubscribed. Opens on the book as it stands; the reader can
 * set where they expect it to close, since most of the bidding comes on the last day.
 */
export function AllotmentOdds({ retailTimes, lotCost }: { retailTimes: number | null; lotCost: number | null }) {
  const market = useMarket();
  const [applications, setApplications] = useState(1);
  const [times, setTimes] = useState(retailTimes != null ? retailTimes.toFixed(2) : "");
  const timesId = useId();
  const parsed = Number.parseFloat(times);
  const odds = allotmentOdds(Number.isFinite(parsed) ? parsed : null, applications);
  const step = "inline-flex size-8 items-center justify-center rounded-md border bg-card text-foreground transition-colors hover:bg-(--control) disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
        <div>
          <p id={`${timesId}-apps`} className="mb-1.5 text-[11px] text-muted-foreground">
            Applications, each from a different PAN
          </p>
          <div className="flex items-center gap-2" role="group" aria-labelledby={`${timesId}-apps`}>
            <button
              type="button"
              className={step}
              onClick={() => setApplications((n) => Math.max(1, n - 1))}
              disabled={applications <= 1}
              aria-label="One application fewer"
            >
              <Minus className="size-3.5" aria-hidden />
            </button>
            <output aria-live="polite" className="tabular w-6 text-center font-mono text-sm font-semibold">
              {applications}
            </output>
            <button
              type="button"
              className={step}
              onClick={() => setApplications((n) => Math.min(MAX_APPLICATIONS, n + 1))}
              disabled={applications >= MAX_APPLICATIONS}
              aria-label="One application more"
            >
              <Plus className="size-3.5" aria-hidden />
            </button>
          </div>
        </div>
        <div>
          <label htmlFor={timesId} className="mb-1.5 block text-[11px] text-muted-foreground">
            Retail book closes at
          </label>
          <div className="flex h-8 items-center rounded-md border bg-card pr-2.5 focus-within:ring-2 focus-within:ring-ring">
            <input
              id={timesId}
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              value={times}
              onChange={(event) => setTimes(event.target.value)}
              className="tabular h-full w-20 rounded-md bg-transparent px-2.5 text-right font-mono text-sm outline-none"
            />
            <span className="font-mono text-sm text-muted-foreground" aria-hidden>
              ×
            </span>
          </div>
        </div>
      </div>

      <div aria-live="polite">
        {odds == null ? (
          <p className="text-sm text-muted-foreground">Enter how many times the retail book is subscribed.</p>
        ) : (
          <>
            <p className="flex items-baseline gap-2">
              <span className="tabular font-mono text-[1.75rem] font-semibold leading-none tracking-[-0.02em]">
                {Math.round(odds * 100)}%
              </span>
              <span className="text-sm text-muted-foreground">chance of at least one lot</span>
            </p>
            {lotCost ? (
              <p className="tabular mt-2 text-xs text-muted-foreground">
                Blocks {formatMoney(lotCost * applications, market, 0)} until allotment
                {applications > 1 ? ` (${formatMoney(lotCost, market, 0)} each)` : ""}; what is not allotted is
                released.
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
