import type { Metadata } from "next";

import { MarketDayNotice } from "@/components/market-day-notice";
import { FiiDiiFlows } from "@/components/market/fii-dii-flows";
import { ForeignDeals } from "@/components/market/foreign-deals";
import { FpiSectorFlows, type SectorTable } from "@/components/market/fpi-sector-flows";
import { foreignDeals, sectorFlows } from "@/lib/fpi-flows.mjs";
import { readLiveBody, readLiveObject } from "@/lib/live-objects";
import { marketFromSlug } from "@/lib/markets";
import { readSectorDirectory } from "@/lib/sector-objects";

export const metadata: Metadata = { title: "Investor flows" };
export const dynamic = "force-dynamic";

/**
 * Who is buying the market and where foreign money is going: NSE's daily
 * FII/DII cash flows, NSDL's fortnightly FPI flows by sector, and the largest
 * foreign bulk and block deals per stock. Two R2 objects (workers/market_flows.py,
 * workers/fpi_flows.py), read as the Breadth page reads its flows; NSE only.
 * Display evidence: a failed read drops its section, never the page.
 */
export default async function FlowsPage({ params }: PageProps<"/[market]/flows">) {
  const market = marketFromSlug((await params).market)!;

  if (market.code !== "NSE") {
    return (
      <div className="space-y-6 px-4 py-5 sm:px-6">
        <h1 className="text-title font-semibold">Investor flows</h1>
        <div className="panel px-5 py-12 text-center">
          <p className="text-sm font-medium">Investor flows are read from NSE and NSDL; there is no US source yet.</p>
        </div>
      </div>
    );
  }

  const [flows, fpi, directory] = await Promise.all([
    readLiveObject(market.code, "fii-dii-flows").catch(() => null),
    readLiveBody(market.code, "fpi-flows").catch(() => null),
    readSectorDirectory(market.code).catch(() => null),
  ]);
  const pages = directory?.sectors.map((sector) => sector.slug) ?? [];
  const table = sectorFlows(fpi?.rows) as SectorTable | null;
  const deals = foreignDeals(fpi);

  return (
    <div className="space-y-8 px-4 py-5 sm:px-6">
      <MarketDayNotice />
      <h1 className="text-title font-semibold">Investor flows</h1>

      {flows?.length ? <FiiDiiFlows market={market} rows={flows} /> : null}

      {table ? (
        <FpiSectorFlows market={market} table={table} pages={pages} />
      ) : (
        <div className="panel px-5 py-12 text-center">
          <p className="text-sm font-medium">FPI flows by sector are not published yet.</p>
          <p className="mt-1 text-xs text-muted-foreground">They appear after the next filings run. Reload later.</p>
        </div>
      )}

      {fpi ? <ForeignDeals market={market} deals={deals} /> : null}
    </div>
  );
}
