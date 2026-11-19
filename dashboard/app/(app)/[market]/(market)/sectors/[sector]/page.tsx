import { notFound } from "next/navigation";

import { SectorView } from "@/components/sectors/sector-view";
import { marketFromSlug } from "@/lib/markets";
import { readSector } from "@/lib/sector-objects";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps<"/[market]/sectors/[sector]">) {
  const { market: slug, sector } = await params;
  const market = marketFromSlug(slug);
  const object = market ? await readSector(market.code, sector) : null;
  return { title: object ? `${object.name} · ${market!.label}` : "Sector" };
}

/** One sector, from its R2 object (lib/sector-objects.ts). */
export default async function SectorPage({ params }: PageProps<"/[market]/sectors/[sector]">) {
  const { market: slug, sector: sectorSlug } = await params;
  const market = marketFromSlug(slug)!;
  const sector = await readSector(market.code, sectorSlug);
  if (!sector) notFound();
  return <SectorView market={market} sector={sector} />;
}
