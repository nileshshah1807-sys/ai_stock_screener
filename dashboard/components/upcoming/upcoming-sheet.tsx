"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { CalendarClock } from "lucide-react";

import { SearchInput } from "@/components/filters/live-search";
import { StockIdentity } from "@/components/stock-identity";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { UpcomingEvent, UpcomingKind } from "@/lib/upcoming";
import { callTime, filterUpcoming, groupUpcoming } from "@/lib/upcoming.mjs";
import { cn } from "@/lib/utils";

/** Companies a day shows before "+N more"; a peak results day holds about 200. */
const DAY_LIMIT = 7;

const COPY = {
  results: {
    title: "Upcoming results",
    blurb: "Board meetings that will approve quarterly results, by the date the company gave the exchange.",
    empty: "No results are lined up.",
    noun: "results",
    quiet: "No results",
  },
  call: {
    title: "Upcoming concalls",
    blurb: "Earnings calls the companies have told the exchange they will hold.",
    empty: "No calls are lined up.",
    noun: "calls",
    quiet: "No calls",
  },
} as const;

export type UpcomingList = { id: string; name: string; symbols: string[] };

/** "Sat 31 Oct", from a calendar day: the day is the company's, so no time zone moves it. */
function dayLabel(iso: string) {
  return new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(`${iso}T00:00:00Z`),
  );
}

function Day({
  group,
  kind,
}: {
  group: { date: string; isToday: boolean; rows: UpcomingEvent[] };
  kind: UpcomingKind;
}) {
  const [all, setAll] = useState(false);
  const copy = COPY[kind];
  const shown = all ? group.rows : group.rows.slice(0, DAY_LIMIT);
  const rest = group.rows.length - shown.length;
  return (
    <section aria-label={dayLabel(group.date)} className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {dayLabel(group.date)}
        {group.isToday ? (
          <span className="rounded bg-caution/15 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-caution">
            TODAY
          </span>
        ) : null}
        <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">
          {group.rows.length ? group.rows.length : copy.quiet}
        </span>
      </h3>
      {group.rows.length ? (
        <ul className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
          {shown.map((row) => {
            const time = kind === "call" ? callTime(row.event_time) : null;
            return (
              <li key={row.symbol} className="flex min-w-0 items-center gap-2">
                <StockIdentity symbol={row.symbol} company={row.company} className="min-w-0 flex-1" />
                {kind === "call" ? (
                  <span className={cn("tabular shrink-0 font-mono text-xs", time ? "" : "text-muted-foreground")}>
                    {time ?? "time TBA"}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {rest > 0 ? (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="rounded text-xs font-medium text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          +{rest} more
        </button>
      ) : null}
    </section>
  );
}

const OpenContext = createContext<(open: boolean) => void>(() => {});

/** Anything that opens the page's Upcoming sheet: the button, and the tiles. */
export function UpcomingTrigger({ className, children }: { className?: string; children: ReactNode }) {
  const setOpen = useContext(OpenContext);
  return (
    <button type="button" onClick={() => setOpen(true)} className={className}>
      {children}
    </button>
  );
}

export function UpcomingButton() {
  return (
    <UpcomingTrigger className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-background px-2.5 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <CalendarClock className="size-3.5 text-muted-foreground" aria-hidden />
      Upcoming
    </UpcomingTrigger>
  );
}

/**
 * The sheet of one page's upcoming list, and what opens it: wrap the page's
 * header and tiles in this, and any UpcomingTrigger inside opens the sheet.: one list, by day, of what the
 * exchange has been told is coming. Searchable, and narrowed to a watchlist by
 * its chip. Days with nothing on them fold into a single line.
 *
 * The rows arrive with the page (a peak week is under a thousand), so
 * searching and switching list answer on the keystroke.
 */
export function UpcomingProvider({
  kind,
  rows,
  today,
  lists,
  defaultOpen = false,
  children,
}: {
  kind: UpcomingKind;
  rows: UpcomingEvent[];
  today: string;
  lists: UpcomingList[];
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const copy = COPY[kind];
  const [open, setOpen] = useState(defaultOpen);
  const [search, setSearch] = useState("");
  const [listId, setListId] = useState<string | null>(null);
  const symbols = lists.find((list) => list.id === listId)?.symbols ?? null;
  const kept = filterUpcoming(rows, { search, symbols });
  const groups = groupUpcoming(kept, today) as (
    | { date: string; isToday: boolean; rows: UpcomingEvent[] }
    | { gap: true; from: string; to: string; days: number }
  )[];

  return (
    <OpenContext.Provider value={setOpen}>
      {children}
      <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="gap-0 data-[side=right]:w-[calc(100vw-1rem)] data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="space-y-1 border-b p-4 pr-12">
          <SheetTitle className="text-base">{copy.title}</SheetTitle>
          <SheetDescription className="text-xs">{copy.blurb}</SheetDescription>
        </SheetHeader>
        <div className="space-y-3 border-b p-4">
          <SearchInput
            value={search}
            onChange={setSearch}
            label={`Search ${copy.noun} by company or symbol`}
            placeholder="Search a company or symbol"
          />
          {lists.length ? (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Watchlist">
              {[{ id: null, name: "All companies" }, ...lists].map((list) => (
                <button
                  key={list.id ?? "all"}
                  type="button"
                  aria-pressed={list.id === listId}
                  onClick={() => setListId(list.id)}
                  className={cn(
                    "h-7 rounded-md border px-2.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    list.id === listId ? "border-foreground bg-muted" : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {list.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {kept.length ? (
            groups.map((group) =>
              "gap" in group ? (
                <p key={group.from} className="text-xs text-muted-foreground">
                  {group.days === 1
                    ? `${dayLabel(group.from)} · ${copy.quiet.toLowerCase()}`
                    : `${dayLabel(group.from)} – ${dayLabel(group.to)} · ${copy.quiet.toLowerCase()}`}
                </p>
              ) : (
                <Day key={group.date} group={group} kind={kind} />
              ),
            )
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {search || symbols ? `No ${copy.noun} match.` : copy.empty}
            </p>
          )}
        </div>
      </SheetContent>
      </Sheet>
    </OpenContext.Provider>
  );
}
