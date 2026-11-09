import { HomeCard } from "@/components/home/home-card";
import { MoversBody } from "@/components/home/movers-body";
import { isAdmin } from "@/lib/auth";
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
  // Ranks are admin-only on Home: dropped here, so a non-admin's page
  // payload never carries them.
  const admin = await isAdmin();
  const hideRank = <T extends { investment_rank: number | null }>(row: T): T => (admin ? row : { ...row, investment_rank: null });
  const safeMonthly = Object.fromEntries(
    Object.entries(monthly).map(([name, lists]) => [name, { gainers: lists.gainers.map(hideRank), losers: lists.losers.map(hideRank) }]),
  );
  const safeLive = live && {
    ...live,
    indices: live.indices.map((index) => ({ ...index, gainers: index.gainers.map(hideRank), losers: index.losers.map(hideRank) })),
  };
  return (
    <HomeCard title="Top movers">
      <MoversBody market={market} initial={safeLive} monthly={safeMonthly} />
    </HomeCard>
  );
}
