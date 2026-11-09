import { HomeCard } from "@/components/home/home-card";
import { UpcomingProvider } from "@/components/upcoming/upcoming-sheet";
import { ResultsLinedUpTile } from "@/components/upcoming/upcoming-tiles";
import { addDays, marketToday } from "@/lib/home";
import type { Market } from "@/lib/markets";
import { getDeclaredSymbols } from "@/lib/results";
import { quarterEnds, quarterWindow } from "@/lib/results.mjs";
import { getUpcoming } from "@/lib/upcoming";
import { notDeclared } from "@/lib/upcoming.mjs";
import { getWatchlists } from "@/lib/watchlists";

const WEEK_DAYS = 7;

/**
 * Results due in the next seven days, as the Results page's tile: a company
 * that has already declared this quarter is not lined up. The tile opens the
 * Results page's full list of upcoming dates.
 */
export async function LinedUpCard({ market }: { market: Market }) {
  const today = marketToday(market);
  const quarter = quarterEnds(today)[0];
  const [dated, declared, lists] = await Promise.all([
    getUpcoming(market.code, "results", today),
    getDeclaredSymbols(market.code, quarter),
    getWatchlists(market.code),
  ]);
  if (!dated) return null;
  // A US company reporting after the quarter's window is for a later quarter.
  const remaining = notDeclared(dated, declared, market.code === "US" ? quarterWindow(quarter).through : null);
  const week = remaining.filter((row) => row.event_date < addDays(today, WEEK_DAYS));
  if (!week.length) return null;

  return (
    <HomeCard title="Lined up this week" note="results due">
      <UpcomingProvider
        kind="results"
        rows={remaining}
        today={today}
        lists={lists.filter((list) => list.symbols.length).map(({ id, name, symbols }) => ({ id, name, symbols }))}
      >
        <ResultsLinedUpTile lined={week.length} declared={null} soonest={[]} logos={new Map()} />
      </UpcomingProvider>
    </HomeCard>
  );
}
