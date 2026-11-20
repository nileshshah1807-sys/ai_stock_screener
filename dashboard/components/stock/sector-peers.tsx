import { SectorPeersPanel, type PeerSlice } from "@/components/stock/sector-peers-panel";
import type { Market } from "@/lib/markets";
import type { SectorObject } from "@/lib/sector-objects";
import { peerSlice } from "@/lib/sectors.mjs";

/** Tiles in the preview: enough to show the sector's shape, few enough to read. */
const PEERS = 24;

/**
 * The stock among its sector, on the stock page: its change beside the
 * sector's own index, its place by size, its P/E beside the sector median,
 * and a small heatmap of the largest members with this one outlined. It is
 * the door to the sector page, which a reader otherwise had no reason to
 * find. From the sector's R2 object (lib/sector-objects.ts); display
 * evidence, no rating. The slice is cut here so that only the tiles shown,
 * not every member and the level series, are sent to the browser.
 */
export function SectorPeers({ market, sector, symbol }: { market: Market; sector: SectorObject; symbol: string }) {
  const slice: Omit<PeerSlice, "own"> & { own: PeerSlice["own"] | null } = peerSlice(sector.members, symbol, PEERS);
  if (!slice.own) return null;
  const { name, slug, count, last_session, d1, y1 } = sector;
  return (
    <SectorPeersPanel
      market={market}
      sector={{ name, slug, count, last_session, d1, y1, median_pe: sector.summary.median_pe }}
      slice={{ ...slice, own: slice.own }}
      symbol={symbol}
    />
  );
}
