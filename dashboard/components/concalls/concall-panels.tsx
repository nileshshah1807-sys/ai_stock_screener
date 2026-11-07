import Link from "next/link";
import { Radio } from "lucide-react";

import { StockIdentity } from "@/components/stock-identity";
import { formatDate } from "@/lib/format";
import type { LiveCall } from "@/lib/live-calls";
import type { UpcomingEvent } from "@/lib/upcoming";
import { callTime, groupUpcoming } from "@/lib/upcoming.mjs";

/** Days of the Upcoming view: a peak week lists about 100 calls a day, and the rest is a click away. */
const UPCOMING_DAYS = 7;

/** "TCS at 15:30 today" -- the next call, named, for an empty Live now. */
function nextCallLine(next: UpcomingEvent, today: string) {
  const time = callTime(next.event_time);
  const day = next.event_date === today ? "today" : `on ${formatDate(next.event_date)}`;
  return `${next.symbol}${time ? ` at ${time} IST` : ""} ${day}`;
}

export function LiveNowPanel({
  calls,
  sample,
  next,
  today,
  base,
  logos,
}: {
  calls: LiveCall[];
  sample: boolean;
  next: UpcomingEvent | null;
  today: string;
  /** The Concalls page's path. */
  base: string;
  logos: Map<string, string | null>;
}) {
  if (!calls.length) {
    return (
      <div className="panel px-5 py-10 text-center">
        <p className="text-sm font-medium">No call is live right now.</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {next ? (
            <>
              Next: {nextCallLine(next, today)}.{" "}
              <Link
                href={`${base}?view=upcoming`}
                className="rounded font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                See what is coming
              </Link>
            </>
          ) : (
            "No call is scheduled yet."
          )}
        </p>
      </div>
    );
  }
  return (
    <section className="panel overflow-hidden" aria-label="Calls on air">
      {sample ? (
        <p className="border-b bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
          Sample call: the live-call tables are not applied to this preview.
        </p>
      ) : null}
      <ul className="divide-y">
        {calls.map((call) => (
          <li key={call.call_id} className="flex items-center gap-3 px-4 py-3">
            <StockIdentity symbol={call.symbol} logoDomain={logos.get(call.symbol)} link={false} className="min-w-0 flex-1" />
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-negative">
              <Radio className="size-3.5" aria-hidden /> On air
            </span>
            <Link
              href={`${base}/live/${encodeURIComponent(call.call_id)}`}
              className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Follow live<span className="sr-only"> {call.symbol}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function UpcomingPanel({ events, today }: { events: UpcomingEvent[] | null; today: string }) {
  const days = (groupUpcoming(events ?? [], today) as { date: string; isToday?: boolean; rows?: UpcomingEvent[] }[])
    .filter((group) => group.rows?.length)
    .slice(0, UPCOMING_DAYS);
  if (!days.length) {
    return (
      <div className="panel px-5 py-10 text-center">
        <p className="text-sm font-medium">No calls scheduled yet.</p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {days.map(({ date, rows = [] }) => (
        <section key={date} className="panel overflow-hidden">
          <h2 className="flex items-center gap-2 border-b px-4 py-3 text-base font-semibold tracking-[-0.011em]">
            {formatDate(date)}
            {date === today ? (
              <span className="rounded bg-caution/15 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-caution">
                TODAY
              </span>
            ) : null}
            <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">{rows.length}</span>
          </h2>
          <ul className="grid gap-x-4 divide-y sm:grid-cols-2 sm:divide-y-0">
            {rows.map((row) => (
              <li key={row.symbol} className="flex min-w-0 items-center gap-2 px-4 py-2">
                <StockIdentity symbol={row.symbol} company={row.company} className="min-w-0 flex-1" />
                <span className="tabular shrink-0 font-mono text-xs text-muted-foreground">
                  {callTime(row.event_time) ?? "time TBA"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
