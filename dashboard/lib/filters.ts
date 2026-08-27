import { parseDensity, parseHiddenColumns } from "@/lib/columns";
import type { ScreenerFilters } from "@/lib/types";

type RawParams = Record<string, string | string[] | undefined>;

function list(value: string | string[] | undefined): string[] {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function num(value: string | string[] | undefined): number | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function str(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw?.trim() || undefined;
}

/**
 * Parse URL search params into a filter object.
 *
 * Every filter lives in the URL rather than component state so a view is
 * shareable and survives a reload -- the thing people actually want when they
 * find a screen worth showing someone else.
 */
export function parseFilters(params: RawParams): ScreenerFilters {
  const dir = str(params.dir);

  return {
    q: str(params.q),
    rating: list(params.rating),
    sector: list(params.sector),
    minScore: num(params.minScore),
    maxScore: num(params.maxScore),
    actionableOnly: str(params.actionable) === "1",
    buyEligibleOnly: str(params.buyEligible) === "1",
    excludeCapped: str(params.excludeCapped) === "1",
    hasTranscript: str(params.transcript) === "1",
    redFlagsOnly: str(params.redFlags) === "1",
    minQuality: num(params.minQuality),
    minMomentum: num(params.minMomentum),
    eligibility: list(params.eligibility),
    aboveMa200: str(params.aboveMa200) === "1",
    sort: str(params.sort) ?? "investment_rank",
    dir: dir === "asc" || dir === "desc" ? dir : undefined,
    page: Math.max(1, num(params.page) ?? 1),
    hiddenColumns: parseHiddenColumns(str(params.cols)),
    density: parseDensity(str(params.density)),
  };
}

/** Rebuild a URLSearchParams from raw params, for links that must preserve state. */
export function toSearchParams(params: RawParams): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item) search.append(key, item);
    }
  }
  return search;
}
