import { BreadthBody } from "@/components/home/breadth-body";
import { HomeCard } from "@/components/home/home-card";
import { getBreadthNow } from "@/lib/home-market";
import type { Market } from "@/lib/markets";

/** How much of the market is trending up: a headline pair from the Market page's breadth. */
export async function BreadthCard({ market }: { market: Market }) {
  const now = await getBreadthNow(market.code);
  if (!now) return null;
  return (
    <HomeCard title="Breadth">
      <BreadthBody now={now} />
    </HomeCard>
  );
}
