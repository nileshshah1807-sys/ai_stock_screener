import { ToolsNav } from "@/components/tools-nav";
import { marketFromSlug } from "@/lib/markets";

/**
 * Tools: views that look across the market rather than rank its stocks.
 *
 * A route group, so the URLs stay `/nse/market` and `/nse/concalls`. The
 * header gives the group one tab, because the primary nav holds five and a
 * tab per tool would not fit; this layout adds the row that says which tool
 * is open. Being a layout, that row does not re-render when moving between
 * tools.
 */
export default async function ToolsLayout({ params, children }: LayoutProps<"/[market]">) {
  const market = marketFromSlug((await params).market)!;

  return (
    <>
      <div className="px-4 pt-5 sm:px-6">
        <ToolsNav market={market} />
      </div>
      {children}
    </>
  );
}
