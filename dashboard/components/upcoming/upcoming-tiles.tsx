import { CompanyLogo } from "@/components/company-logo";
import { UpcomingTrigger } from "@/components/upcoming/upcoming-sheet";
import { formatInteger } from "@/lib/format";
import type { UpcomingEvent } from "@/lib/upcoming";
import { callTime } from "@/lib/upcoming.mjs";

/** A figure above a list; it opens that list. Spans only: it is a button. */
function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <UpcomingTrigger className="panel block min-w-0 max-w-sm flex-1 basis-56 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="block text-xs text-muted-foreground">{label}</span>
      {children}
    </UpcomingTrigger>
  );
}

/** "Results lined up": from today on, against what has been declared this season. */
export function ResultsLinedUpTile({
  lined,
  declared,
  soonest,
  logos,
}: {
  lined: number;
  declared: number | null;
  /** The first companies to report, for the logos. */
  soonest: UpcomingEvent[];
  logos: Map<string, string | null>;
}) {
  const total = declared === null ? null : declared + lined;
  return (
    <Tile label="Results lined up">
      <span className="mt-1 flex items-center gap-3">
        <span className="tabular text-2xl font-semibold tracking-tight">{formatInteger(lined)}</span>
        <span className="flex -space-x-1.5" aria-hidden>
          {soonest.slice(0, 4).map((row) => (
            <CompanyLogo key={row.symbol} symbol={row.symbol} domain={logos.get(row.symbol)} className="size-6 rounded-md ring-2 ring-card" />
          ))}
        </span>
      </span>
      {declared !== null && total ? (
        <>
          <span className="mt-2 block h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
            <span className="block h-full bg-foreground/60" style={{ width: `${(declared / total) * 100}%` }} />
          </span>
          <span className="tabular mt-1.5 block text-xs text-muted-foreground">
            {formatInteger(declared)} declared so far this season
          </span>
        </>
      ) : null}
    </Tile>
  );
}

/** "Next concall": the first call still to come, with its time or that none was stated. */
export function NextConcallTile({
  next,
  today,
  logoDomain,
}: {
  next: UpcomingEvent;
  today: string;
  logoDomain: string | null | undefined;
}) {
  const time = callTime(next.event_time);
  const when =
    next.event_date === today
      ? "Today"
      : new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
          new Date(`${next.event_date}T00:00:00Z`),
        );
  return (
    <Tile label="Next concall">
      <span className="mt-1 flex items-center gap-2.5">
        <CompanyLogo symbol={next.symbol} domain={logoDomain} className="size-8" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">{next.company ?? next.symbol}</span>
          <span className="tabular block text-xs text-muted-foreground">
            {when} · {time ?? "time TBA"}
          </span>
        </span>
      </span>
    </Tile>
  );
}
