"use client";

import { useEffect, useState } from "react";

import { MarketDayNotice } from "@/components/market-day-notice";
import { useMarket } from "@/components/market-provider";
import { FiiDiiFlows } from "@/components/market/fii-dii-flows";
import { ForeignDeals } from "@/components/market/foreign-deals";
import { FpiSectorFlows, type SectorTable } from "@/components/market/fpi-sector-flows";
import { PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";
import { readObject } from "@/lib/browser-objects";
import { foreignDeals, sectorFlows } from "@/lib/fpi-flows.mjs";

type Rows = { rows?: Record<string, unknown>[] } & Record<string, unknown>;
type Loaded = { flows: Rows | null; fpi: Rows | null; directory: { sectors?: { slug: string }[] } | null };

/** Heading, daily flows, sector table: the shape of the page while it loads. */
export function FlowsSkeleton() {
  return (
    <div className="space-y-8 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading investor flows…</span>
      <PageHeadingSkeleton />
      <Skeleton className="h-[230px] w-full rounded-lg" />
      <Skeleton className="h-[560px] w-full rounded-lg" />
    </div>
  );
}

/**
 * Who is buying the market and where foreign money is going: NSE's daily FII/DII
 * cash flows, NSDL's fortnightly FPI flows by sector, and the largest foreign bulk
 * and block deals per stock. Three R2 objects (workers/market_flows.py,
 * workers/fpi_flows.py, workers/sectors.py), read in the browser through
 * /api/objects; NSE only. Display evidence: a failed read drops its section, never the page.
 */
export function FlowsView() {
  const market = useMarket();
  const [data, setData] = useState<Loaded | null>(null);
  const nse = market.code === "NSE";

  useEffect(() => {
    if (!nse) return;
    let current = true;
    Promise.all([
      readObject<Rows>(market.code, "fii-dii-flows"),
      readObject<Rows>(market.code, "fpi-flows"),
      readObject<Loaded["directory"]>(market.code, "sector-directory"),
    ]).then(([flows, fpi, directory]) => {
      if (current) setData({ flows, fpi, directory });
    });
    return () => {
      current = false;
    };
  }, [market.code, nse]);

  if (!nse) {
    return (
      <div className="space-y-6 px-4 py-5 sm:px-6">
        <h1 className="text-title font-semibold">Investor flows</h1>
        <div className="panel px-5 py-12 text-center">
          <p className="text-sm font-medium">Investor flows are read from NSE and NSDL; there is no US source yet.</p>
        </div>
      </div>
    );
  }
  if (!data) return <FlowsSkeleton />;

  const flows = data.flows?.rows ?? null;
  const pages = data.directory?.sectors?.map((sector) => sector.slug) ?? [];
  const table = sectorFlows(data.fpi?.rows) as SectorTable | null;
  const deals = foreignDeals(data.fpi);

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

      {data.fpi ? <ForeignDeals market={market} deals={deals} /> : null}
    </div>
  );
}
