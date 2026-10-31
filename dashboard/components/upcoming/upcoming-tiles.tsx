import { CompanyLogo } from "@/components/company-logo";
import { formatInteger } from "@/lib/format";
import type { UpcomingEvent } from "@/lib/upcoming";
import { callTime } from "@/lib/upcoming.mjs";

/** One quiet line above a list: a number, what it counts, and what it sits beside. */
function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="panel min-w-0 flex-1 basis-56 px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      {children}
    </div>
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
      <div className="mt-1 flex items-center gap-3">
        <p className="tabular text-2xl font-semibold tracking-tight">{formatInteger(lined)}</p>
        <div className="flex -space-x-1.5" aria-hidden>
          {soonest.slice(0, 4).map((row) => (
            <CompanyLogo key={row.symbol} symbol={row.symbol} domain={logos.get(row.symbol)} className="size-6 rounded-md ring-2 ring-card" />
          ))}
        </div>
      </div>
      {declared !== null && total ? (
        <>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full bg-foreground/60" style={{ width: `${(declared / total) * 100}%` }} />
          </div>
          <p className="tabular mt-1.5 text-xs text-muted-foreground">
            {formatInteger(declared)} declared so far this season
          </p>
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
      <div className="mt-1 flex items-center gap-2.5">
        <CompanyLogo symbol={next.symbol} domain={logoDomain} className="size-8" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{next.company ?? next.symbol}</p>
          <p className="tabular text-xs text-muted-foreground">
            {when} · {time ?? "time not stated"}
          </p>
        </div>
      </div>
    </Tile>
  );
}
