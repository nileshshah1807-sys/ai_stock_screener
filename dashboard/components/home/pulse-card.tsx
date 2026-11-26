import { LiveTicker } from "@/components/home/live-ticker";
import { PulseTiles } from "@/components/home/pulse-table";
import { getPulseIndices } from "@/lib/home-market";
import type { Market } from "@/lib/markets";
import { getLiveMarket } from "@/lib/queries";

/**
 * The market band: headline index levels with today's line and 1D, 1W and 1M
 * change, and the day's movers gliding beneath. The movers are the read the
 * Top movers card makes too (`getLiveMarket` is cached per request).
 */
export async function PulseCard({ market }: { market: Market }) {
  const [indices, { live }] = await Promise.all([getPulseIndices(market.code), getLiveMarket(market.code)]);
  if (!indices.length) return null;
  return (
    <section aria-label="Market pulse" className="panel flex animate-rise flex-col p-4 sm:p-5">
      <PulseTiles indices={indices} />
      <LiveTicker initial={live} />
    </section>
  );
}
