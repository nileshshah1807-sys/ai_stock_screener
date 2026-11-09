import { StockIdentity } from "@/components/stock-identity";
import { addDays, marketToday } from "@/lib/home";
import { groupEventsByDate } from "@/lib/home.mjs";
import type { Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";
import { getUpcoming, type UpcomingEvent } from "@/lib/upcoming";
import { callTime } from "@/lib/upcoming.mjs";

const WINDOW_DAYS = 14;

/**
 * Result dates and earnings calls in the next two weeks for the stocks the
 * viewer watches. Reads the same `upcoming_events` rows as the Results page's
 * list; a card with nothing in the window renders nothing.
 */
export async function ComingUpCard({ market }: { market: Market }) {
  const today = marketToday(market);
  const until = addDays(today, WINDOW_DAYS);
  const [watched, results, calls] = await Promise.all([
    getWatchedSymbols(market.code),
    getUpcoming(market.code, "results", today),
    getUpcoming(market.code, "call", today),
  ]);
  const mine = new Set(watched);
  const events: UpcomingEvent[] = [...(results ?? []), ...(calls ?? [])]
    .filter((event) => mine.has(event.symbol) && event.event_date <= until)
    .sort((a, b) => a.event_date.localeCompare(b.event_date) || a.symbol.localeCompare(b.symbol));
  if (!events.length) return null;

  const days = groupEventsByDate(events);

  return (
    <section aria-label="Coming up, next 14 days" className="panel animate-rise p-4 sm:p-5">
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-[-0.01em]">Coming up</h2>
        <span className="tabular text-xs text-muted-foreground">your stocks, next 14 days</span>
      </header>
      <ol className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 sm:-mx-5 sm:px-5">
        {days.map(({ date, events: list }, position) => (
          <li
            key={date}
            className="min-w-44 shrink-0 snap-start animate-rise rounded-xl border border-border bg-background/40 p-3"
            style={{ animationDelay: `${Math.min(position, 6) * 50}ms` }}
          >
            <p className="flex items-baseline gap-2">
              <span className="tabular text-lg font-semibold leading-none">{dayOf(date)}</span>
              <span className="text-xs text-muted-foreground">{date === today ? "Today" : weekdayOf(date, market.locale)}</span>
            </p>
            <ul className="mt-2 space-y-1.5">
              {list.map((event) => (
                <li key={`${event.kind}:${event.symbol}`} className="flex items-center gap-2">
                  <StockIdentity symbol={event.symbol} company={event.company} className="min-w-0 flex-1" />
                  <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {event.kind === "call" ? `Call${event.event_time ? ` · ${callTime(event.event_time)}` : ""}` : "Results"}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}

const dayOf = (date: string) => new Date(`${date}T00:00:00Z`).getUTCDate();
const weekdayOf = (date: string, locale: string) =>
  new Date(`${date}T00:00:00Z`).toLocaleDateString(locale, { weekday: "short", month: "short", timeZone: "UTC" });
