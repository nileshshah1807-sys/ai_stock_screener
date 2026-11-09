import { EventRow } from "@/components/notifications/event-row";
import { HomeCard } from "@/components/home/home-card";
import { getBellState } from "@/lib/notifications";
import { describeEvent } from "@/lib/notifications.mjs";
import type { Market } from "@/lib/markets";

/**
 * What changed on the viewer's lists since they last opened the feed. It is the
 * bell's own state (`getBellState`, cached per request), so the count here is
 * the number on the bell and costs no extra read.
 */
export async function SinceCard({ market }: { market: Market }) {
  const state = await getBellState(market.code);
  const { unread, seenAt } = state;
  // The same call can be recorded twice (a recording, then the filed
  // transcript): one line per stock, kind and what it says.
  const seenLines = new Set<string>();
  const events = state.events.filter((event) => {
    const { title, summary } = describeEvent(event);
    const line = `${event.symbol}|${event.kind}|${title}|${summary}`;
    return seenLines.has(line) ? false : (seenLines.add(line), true);
  });
  if (!events.length) return null;
  const seen = seenAt ? Date.parse(seenAt) : 0;

  return (
    <HomeCard title="Since you last visited" note={unread ? `${unread} new` : "All caught up"}>
      <ul className="-mx-4 divide-y divide-border sm:-mx-5">
        {events.map((event) => (
          <li key={event.id}>
            <EventRow event={event} market={market} unread={Date.parse(event.detected_at) > seen} time={null} />
          </li>
        ))}
      </ul>
    </HomeCard>
  );
}
