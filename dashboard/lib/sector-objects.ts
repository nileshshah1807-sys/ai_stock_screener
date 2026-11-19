import "server-only";

import { getCloudflareContext } from "@opennextjs/cloudflare";

import { getViewer } from "@/lib/auth";
import type { MarketCode } from "@/lib/markets";
import { sharedMemo } from "@/lib/shared-memo.mjs";

/**
 * The sector pages' data: R2 objects only, written once an evening by
 * tools/publish_market_breadth.py (workers/sectors.py). No table, no
 * Supabase read. `sectors/{MARKET}/directory.json` lists every sector;
 * `sectors/{MARKET}/{slug}.json` holds one sector's level, valuation and
 * members.
 *
 * The objects bypass row-level security, so the viewer's access is checked
 * here before anything is read. They carry no rating, rank or score.
 */

/** A sector as the directory lists it. Changes are percent; null where the level does not reach back. */
export type SectorEntry = {
  name: string;
  slug: string;
  last_session: string | null;
  d1: number | null;
  m1: number | null;
  y1: number | null;
  count: number;
  total_cap: number | null;
  advancing: number;
  declining: number;
  traded: number;
};

export type SectorDirectory = { market: MarketCode; run_date: string; sectors: SectorEntry[] };

/** One member. `pct` fields (d1, m3, y1, dy) are percent; roe and rg are ratios. */
export type SectorMember = {
  s: string;
  c: string | null;
  mc: number | null;
  pe: number | null;
  pb: number | null;
  roe: number | null;
  dy: number | null;
  rg: number | null;
  d1: number | null;
  m3: number | null;
  y1: number | null;
  tv: number | null;
};

export type SectorObject = SectorEntry & {
  market: MarketCode;
  run_date: string;
  summary: {
    count: number;
    total_cap: number | null;
    cap_weighted_pe: number | null;
    median_pe: number | null;
    median_pb: number | null;
    median_roe: number | null;
    median_yield: number | null;
    no_positive_pe: number;
    advancing: number;
    declining: number;
    traded: number;
  };
  pe_buckets: { label: string; count: number }[];
  /** The cap-weighted level as `market_breadth` encodes an index row (metric `c`, hundredths). */
  level: { sessions: string; series: string } | null;
  members: SectorMember[];
};

type R2Bucket = { get(key: string): Promise<{ text(): Promise<string> } | null> };

/** Written once an evening; five minutes keeps every viewer on one parse per instance. */
const memo = sharedMemo<unknown>(300_000, 40);

const SLUG = /^[a-z0-9-]{1,80}$/;

async function load<T>(path: string): Promise<T | null> {
  let bucket: R2Bucket | undefined;
  try {
    bucket = (getCloudflareContext().env as Record<string, unknown>).MARKET_DATA as R2Bucket | undefined;
  } catch {
    bucket = undefined;
  }
  if (!bucket) {
    console.warn(`sector objects: no MARKET_DATA binding for ${path}`);
    return null;
  }
  const object = await bucket.get(path);
  return object ? (JSON.parse(await object.text()) as T) : null;
}

async function read<T>(market: MarketCode, name: string): Promise<T | null> {
  if (!(await getViewer())) return null;
  const path = `sectors/${market}/${name}.json`;
  return memo(path, () => load<T>(path), (value) => value !== null) as Promise<T | null>;
}

/** Every sector of the market, or null when the directory has not been published. */
export function readSectorDirectory(market: MarketCode): Promise<SectorDirectory | null> {
  return read<SectorDirectory>(market, "directory");
}

/** One sector by its slug, or null when there is none. */
export function readSector(market: MarketCode, slug: string): Promise<SectorObject | null> {
  if (!SLUG.test(slug) || slug === "directory") return Promise.resolve(null);
  return read<SectorObject>(market, slug);
}
