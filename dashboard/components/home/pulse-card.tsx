import { PulseTiles } from "@/components/home/pulse-table";
import { getPulseIndices } from "@/lib/home-market";
import type { Market } from "@/lib/markets";

/** The market band: headline index levels with a month's line and 1D, 1W and 1M change. */
export async function PulseCard({ market }: { market: Market }) {
  const indices = await getPulseIndices(market.code);
  if (!indices.length) return null;
  return (
    <section aria-label="Market pulse" className="panel animate-rise p-4 sm:p-5">
      <PulseTiles indices={indices} />
    </section>
  );
}
