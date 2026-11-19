import type { Metadata } from "next";

import { SectorsView } from "@/components/sectors/sectors-view";
import { marketFromSlug } from "@/lib/markets";
import { readSectorDirectory } from "@/lib/sector-objects";

export const metadata: Metadata = { title: "Sectors" };
export const dynamic = "force-dynamic";

/**
 * Every sector of the market: our own cap-weighted index for each, built
 * from every stock the screener tracks, as a heatmap and a table. Read from
 * one R2 object (lib/sector-objects.ts); display evidence only.
 */
export default async function SectorsPage({ params }: PageProps<"/[market]/sectors">) {
  const market = marketFromSlug((await params).market)!;
  const directory = await readSectorDirectory(market.code);
  return <SectorsView market={market} sectors={directory?.sectors ?? []} />;
}
