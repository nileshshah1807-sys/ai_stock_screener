import { ResultsTabs } from "@/components/results/results-tabs";
import { marketFromSlug, marketPath } from "@/lib/markets";

/** Results and its Analysis, under one tab row; a layout, so moving between them keeps it. */
export default async function ResultsLayout({ params, children }: LayoutProps<"/[market]/results">) {
  const market = marketFromSlug((await params).market)!;
  // The US has no results to analyse either (the page says why).
  return (
    <>
      {market.code === "NSE" ? (
        <div className="px-4 pt-4 sm:px-6">
          <ResultsTabs base={marketPath(market.slug, "/results")} />
        </div>
      ) : null}
      {children}
    </>
  );
}
