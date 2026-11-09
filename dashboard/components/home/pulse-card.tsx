import { HomeCard } from "@/components/home/home-card";
import { PulseTable } from "@/components/home/pulse-table";
import { getPulseIndices } from "@/lib/home-market";
import type { Market } from "@/lib/markets";

/** Headline index levels with their 1D, 1W and 1M change, and whether the market is open. */
export async function PulseCard({ market }: { market: Market }) {
  const indices = await getPulseIndices(market.code);
  if (!indices.length) return null;
  return (
    <HomeCard title="Market pulse">
      <PulseTable indices={indices} />
    </HomeCard>
  );
}
