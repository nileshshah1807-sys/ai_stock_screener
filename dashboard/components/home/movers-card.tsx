import { HomeCard } from "@/components/home/home-card";
import { MoversBody } from "@/components/home/movers-body";
import { getMonthlyMovers } from "@/lib/home-market";
import type { Market } from "@/lib/markets";
import { getLiveMarket } from "@/lib/queries";

/**
 * Top movers by index: today's from the live quotes, the month's from the
 * run. Nothing for a market with no live indices and no stored month.
 */
export async function MoversCard({ market }: { market: Market }) {
  const { live } = await getLiveMarket(market.code);
  const monthly = await getMonthlyMovers(market.code, live?.indices.map((entry) => entry.name) ?? []);
  if (!live && !Object.keys(monthly).length) return null;
  return (
    <HomeCard title="Top movers">
      <MoversBody market={market} initial={live} monthly={monthly} />
    </HomeCard>
  );
}
