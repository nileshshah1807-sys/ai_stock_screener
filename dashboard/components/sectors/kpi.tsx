import { cn } from "@/lib/utils";

/** One figure of a KPI band. `tone` colours a change; `share` draws a thin part-of-whole bar under it. */
export type Kpi = {
  label: string;
  value: string;
  hint?: string;
  tone?: number | null;
  share?: number | null;
};

/**
 * Figures in one panel with hairline dividers, as the screener's summary
 * band draws them: two to a row on a phone, all in one row from `sm`.
 */
export function KpiBand({ items, className }: { items: Kpi[]; className?: string }) {
  return (
    <dl
      className={cn(
        "panel grid grid-cols-2 divide-border overflow-hidden sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none sm:divide-x",
        className,
      )}
    >
      {items.map((item) => (
        <div key={item.label} className="border-border px-4 py-3 not-last:border-b sm:border-b-0 [&:nth-child(odd)]:border-r sm:[&:nth-child(odd)]:border-r-0">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd
            className={cn(
              "numeral mt-1 text-xl font-semibold leading-tight tracking-[-0.02em]",
              item.tone !== undefined && item.tone !== null && (item.tone >= 0 ? "text-positive" : "text-negative"),
            )}
          >
            {item.value}
          </dd>
          {item.share !== undefined && item.share !== null ? (
            <div className="mt-2 h-1 w-full max-w-36 overflow-hidden rounded-full bg-(--control)" aria-hidden>
              <div className="h-full rounded-full bg-positive" style={{ width: `${Math.round(item.share * 100)}%` }} />
            </div>
          ) : null}
          {item.hint ? <p className="mt-1 text-xs text-muted-foreground">{item.hint}</p> : null}
        </div>
      ))}
    </dl>
  );
}

/** Profitable members counted into P/E buckets, each bar labelled with its count. */
export function PeDistribution({ buckets }: { buckets: { label: string; count: number }[] }) {
  const most = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  return (
    <figure className="panel p-4">
      <figcaption className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">P/E distribution</span>
        <span className="text-xs text-muted-foreground">{total} with a positive P/E</span>
      </figcaption>
      <ol className="mt-4 flex h-36 items-end gap-1.5" aria-label="Stocks per P/E band">
        {buckets.map((bucket) => (
          <li key={bucket.label} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
            <span className="tabular font-mono text-xs text-foreground">{bucket.count}</span>
            <span
              className="w-full max-w-10 rounded-t-[4px] bg-[#6366f1]/70 dark:bg-[#7478ef]/80"
              style={{ height: `${bucket.count ? Math.max(4, (bucket.count / most) * 100) : 0}%` }}
              aria-hidden
            />
            <span className="sr-only">
              P/E {bucket.label}: {bucket.count} stocks
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-1.5 flex gap-1.5 border-t border-border pt-1.5" aria-hidden>
        {buckets.map((bucket) => (
          <span key={bucket.label} className="tabular min-w-0 flex-1 text-center font-mono text-[11px] text-muted-foreground">
            {bucket.label}
          </span>
        ))}
      </div>
    </figure>
  );
}
