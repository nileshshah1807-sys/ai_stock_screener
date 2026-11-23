import { notFound } from "next/navigation";

import { MemberTable, readMembers } from "@/components/screener/member-table";
import { SectorView } from "@/components/sectors/sector-view";
import { marketFromSlug } from "@/lib/markets";
import { getLatestRun } from "@/lib/queries";
import { readSector } from "@/lib/sector-objects";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps<"/[market]/sectors/[sector]">) {
  const { market: slug, sector } = await params;
  const market = marketFromSlug(slug);
  const object = market ? await readSector(market.code, sector) : null;
  return { title: object ? `${object.name} · ${market!.label}` : "Sector" };
}

/**
 * One sector, from its R2 object (lib/sector-objects.ts); its members in the
 * screener's own table, as an index's constituents are.
 */
export default async function SectorPage({ params, searchParams }: PageProps<"/[market]/sectors/[sector]">) {
  const { market: slug, sector: sectorSlug } = await params;
  const market = marketFromSlug(slug)!;
  const [sector, run] = await Promise.all([readSector(market.code, sectorSlug), getLatestRun(market.code)]);
  if (!sector) notFound();
  const members = sector.members.map((member) => ({ symbol: member.s, company: member.c }));
  const table = await readMembers(market.code, run, members, await searchParams);
  return (
    <SectorView
      market={market}
      sector={sector}
      table={
        <MemberTable
          id="members-title"
          title={`All ${sector.summary.count.toLocaleString(market.locale)} stocks`}
          noun="stock"
          data={table}
        />
      }
    />
  );
}
