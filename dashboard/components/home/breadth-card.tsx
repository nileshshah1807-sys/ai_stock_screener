import { BreadthBody } from "@/components/home/breadth-body";
import { getBreadthNow } from "@/lib/home-market";
import type { Market } from "@/lib/markets";

/** How much of the market is trending up: a headline pair from the Market page's breadth. */
export async function BreadthCard({ market }: { market: Market }) {
  const now = await getBreadthNow(market.code);
  if (!now) return null;
  return (
    <section aria-label="Market breadth" className="panel flex h-full animate-rise flex-col p-4 sm:p-5">
      <h2 className="mb-3 text-sm font-semibold tracking-[-0.01em]">Breadth</h2>
      <BreadthBody now={now} />
    </section>
  );
}
