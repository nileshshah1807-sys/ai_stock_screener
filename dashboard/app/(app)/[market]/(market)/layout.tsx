import { SubNav } from "@/components/sub-nav";
import { marketFromSlug } from "@/lib/markets";

/**
 * Market: today's movers, sectors, breadth.
 *
 * A route group, so the URLs stay `/ind/market`, `/ind/sectors` and
 * `/ind/breadth`. One page held all three before, and the sectors heatmap was
 * a small link most readers never found; a row of pages under the Market tab
 * names each one, as the Tools layout does for its tools.
 */
export default async function MarketLayout({ params, children }: LayoutProps<"/[market]">) {
  const market = marketFromSlug((await params).market)!;

  return (
    <>
      <div className="px-4 pt-5 sm:px-6">
        <SubNav group="Market" market={market} admin={false} />
      </div>
      {children}
    </>
  );
}
