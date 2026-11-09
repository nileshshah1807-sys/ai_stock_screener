import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { addDays, marketToday } from "@/lib/home";
import { formatDate } from "@/lib/format";
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

  return (
    <HomeCard title="Coming up" note="next 14 days">
      <ul className="divide-y divide-border">
        {events.slice(0, 8).map((event) => (
          <li key={`${event.kind}:${event.symbol}:${event.event_date}`} className="flex items-center gap-3 py-2">
            <StockIdentity symbol={event.symbol} company={event.company} className="min-w-0 flex-1" />
            <span className="tabular shrink-0 text-right text-xs text-muted-foreground">
              <span className="block text-foreground">{event.kind === "call" ? "Call" : "Results"}</span>
              {formatDate(event.event_date)}
              {event.kind === "call" && event.event_time ? ` · ${callTime(event.event_time)}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </HomeCard>
  );
}
