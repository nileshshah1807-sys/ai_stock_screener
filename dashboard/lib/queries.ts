import "server-only";

import { createClient } from "@/lib/supabase/server";
import type {
  HistoryRow,
  MoverRow,
  ScreenerFilters,
  ScreenerRun,
  SearchEntry,
  SnapshotRow,
  SnapshotRowWithPayload,
} from "@/lib/types";

export const PAGE_SIZE = 100;

/** PostgREST caps a single response; anything universe-wide must be paged. */
const FETCH_CHUNK = 1000;

/** Columns the grid needs. Selecting * would drag `payload` into every list
 *  query and multiply the response size by roughly forty. */
const GRID_COLUMNS = [
  "run_date",
  "symbol",
  "company",
  "sector",
  "investment_rank",
  "actionable_rank",
  "fundamental_score",
  "technical_score",
  "combined_score",
  "evidence_score",
  "decision_score",
  "final_score",
  "rating",
  "buy_eligible",
  "strong_buy_eligible",
  "rating_capped",
  "rating_cap_reason",
  "decision_cap_reason",
  "gate_failure_count",
  "gate_failures",
  "fundamental_coverage",
  "technical_coverage",
  "fund_fields_present",
  "fund_fields_expected",
  "current_price",
  "pct_change_1m",
  "pct_change_3m",
  "market_cap",
  "pe_ratio",
  "dcf_status",
  "dcf_base_case_upside",
  "dcf_valuation_score",
  "transcript_status",
  "transcript_scoring_eligible",
  "transcript_guidance",
  "red_flag_status",
  "red_flag_severity",
  "shadow_red_flag_would_change",
  "liquidity_grade",
  "portfolio_actionable",
  "median_turnover_20d_inr",
  "price_bar_aligned",
  "fund_data_stale",
  // Model 5.0. Null on 4.x rows, so the grid renders these columns only when
  // factor_model_applied is set rather than showing a wall of dashes.
  "factor_model_applied",
  "research_score",
  "quality_percentile",
  "growth_percentile",
  "momentum_percentile",
  "risk_percentile",
  "eligibility_class",
  "primary_gate",
  "gate_severity",
  "research_rating",
  "policy_eligible_rating",
  "execution_status",
  "market_regime",
  "price_to_ma200_pct",
  "ma200_slope_pct",
  "momentum_12_1_pct",
  "rs_market_6m_pct",
  "roic",
].join(",");

const SORTABLE = new Set([
  "investment_rank",
  "actionable_rank",
  "decision_score",
  "final_score",
  "evidence_score",
  "fundamental_score",
  "technical_score",
  "current_price",
  "pct_change_1m",
  "pct_change_3m",
  "market_cap",
  "pe_ratio",
  "dcf_base_case_upside",
  "median_turnover_20d_inr",
  "symbol",
  "company",
  "sector",
  "rating",
  // Model 5.0. eligibility_class ascends by default like the rank columns,
  // because class 0 (clears every gate) is the best, not the worst.
  "research_score",
  "quality_percentile",
  "growth_percentile",
  "momentum_percentile",
  "risk_percentile",
  "eligibility_class",
  "gate_severity",
  "price_to_ma200_pct",
  "momentum_12_1_pct",
  "rs_market_6m_pct",
  "roic",
]);

/** Sort keys where a LOWER value is better, so they default to ascending. */
const ASCENDING_BY_DEFAULT = new Set([
  "eligibility_class",
  "gate_severity",
]);

export async function getLatestRun(): Promise<ScreenerRun | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_runs")
    .select("*")
    .order("run_date", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    console.error("getLatestRun failed", error.message);
    return null;
  }
  return data as ScreenerRun | null;
}

export async function getRecentRuns(limit = 30): Promise<ScreenerRun[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_runs")
    .select("*")
    .order("run_date", { ascending: false })
    .limit(limit);

  if (error) {
    console.error("getRecentRuns failed", error.message);
    return [];
  }
  return (data ?? []) as ScreenerRun[];
}

/**
 * Filtered, sorted, paginated grid read.
 *
 * Filtering runs in Postgres rather than the browser so the page weight stays
 * constant as the universe grows, and so a filter reflects the whole universe
 * rather than whatever subset happened to be loaded.
 */
export async function getSnapshotPage(
  runDate: string,
  filters: ScreenerFilters,
): Promise<{ rows: SnapshotRow[]; total: number }> {
  const supabase = await createClient();

  let query = supabase
    .from("screener_snapshot")
    .select(GRID_COLUMNS, { count: "exact" })
    .eq("run_date", runDate);

  if (filters.q?.trim()) {
    const term = filters.q.trim().replace(/[%,()]/g, "");
    if (term) {
      query = query.or(`symbol.ilike.%${term}%,company.ilike.%${term}%`);
    }
  }
  if (filters.rating?.length) {
    query = query.in("rating", filters.rating);
  }
  if (filters.sector?.length) {
    query = query.in("sector", filters.sector);
  }
  if (typeof filters.minScore === "number") {
    query = query.gte("decision_score", filters.minScore);
  }
  if (typeof filters.maxScore === "number") {
    query = query.lte("decision_score", filters.maxScore);
  }
  if (filters.actionableOnly) {
    query = query.eq("portfolio_actionable", true);
  }
  if (filters.buyEligibleOnly) {
    query = query.eq("buy_eligible", true);
  }
  if (filters.excludeCapped) {
    query = query.or("rating_capped.is.null,rating_capped.eq.false");
  }
  if (filters.hasTranscript) {
    query = query.eq("transcript_scoring_eligible", true);
  }
  if (filters.redFlagsOnly) {
    query = query.gt("red_flag_severity", 0);
  }
  // Model 5.0 filters. On a 4.x run these columns are null, and PostgREST
  // comparison operators exclude nulls, so applying one would empty the grid
  // rather than be ignored. That is the correct behaviour -- the filter asks
  // for evidence the run does not have -- and the filter bar hides these
  // controls entirely unless the run used the factor model.
  if (typeof filters.minQuality === "number") {
    query = query.gte("quality_percentile", filters.minQuality);
  }
  if (typeof filters.minMomentum === "number") {
    query = query.gte("momentum_percentile", filters.minMomentum);
  }
  if (filters.eligibility?.length) {
    const classes = filters.eligibility
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value));
    if (classes.length) {
      query = query.in("eligibility_class", classes);
    }
  }
  if (filters.aboveMa200) {
    query = query.gte("price_to_ma200_pct", 0);
  }

  const sortColumn =
    filters.sort && SORTABLE.has(filters.sort)
      ? filters.sort
      : "investment_rank";
  const ascending = filters.dir
    ? filters.dir === "asc"
    : sortColumn.endsWith("rank") || ASCENDING_BY_DEFAULT.has(sortColumn);

  const page = Math.max(1, filters.page ?? 1);
  const from = (page - 1) * PAGE_SIZE;

  // nullsFirst:false keeps rows with no value for the sort key at the bottom,
  // so an unranked or uncovered stock never displaces a scored one at the top.
  const { data, error, count } = await query
    .order(sortColumn, { ascending, nullsFirst: false })
    .order("symbol", { ascending: true })
    .range(from, from + PAGE_SIZE - 1);

  if (error) {
    console.error("getSnapshotPage failed", error.message);
    return { rows: [], total: 0 };
  }

  return {
    rows: (data ?? []) as unknown as SnapshotRow[],
    total: count ?? 0,
  };
}

/**
 * Slim universe index for instant client-side typeahead.
 *
 * ~2,400 entries at five short fields each compresses to well under 100 KB,
 * which buys a keystroke-latency search with no network round trip. The full
 * grid still filters server-side; this only powers "jump to a stock".
 */
export async function getSearchIndex(runDate: string): Promise<SearchEntry[]> {
  const supabase = await createClient();
  const entries: SearchEntry[] = [];

  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_snapshot")
      .select("symbol, company, investment_rank, rating, decision_score")
      .eq("run_date", runDate)
      .order("investment_rank", { ascending: true, nullsFirst: false })
      .range(offset, offset + FETCH_CHUNK - 1);

    if (error) {
      console.error("getSearchIndex failed", error.message);
      break;
    }
    if (!data?.length) break;

    for (const row of data) {
      entries.push({
        s: row.symbol as string,
        c: (row.company as string) ?? "",
        r: row.investment_rank as number | null,
        g: row.rating as string | null,
        d: row.decision_score as number | null,
      });
    }
    if (data.length < FETCH_CHUNK) break;
  }

  return entries;
}

export async function getStock(
  runDate: string,
  symbol: string,
): Promise<SnapshotRowWithPayload | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_snapshot")
    .select("*")
    .eq("run_date", runDate)
    .eq("symbol", symbol.toUpperCase())
    .maybeSingle();

  if (error) {
    console.error("getStock failed", error.message);
    return null;
  }
  return data as SnapshotRowWithPayload | null;
}

export async function getStockHistory(
  symbol: string,
  limit = 180,
): Promise<HistoryRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_history")
    .select(
      "observed_on, symbol, investment_rank, decision_score, final_score, fundamental_score, technical_score, rating, current_price",
    )
    .eq("symbol", symbol.toUpperCase())
    .order("observed_on", { ascending: false })
    .limit(limit);

  if (error) {
    console.error("getStockHistory failed", error.message);
    return [];
  }
  // Reversed so charts read left-to-right in time order.
  return ((data ?? []) as HistoryRow[]).reverse();
}

export async function getSectors(runDate: string): Promise<string[]> {
  const supabase = await createClient();
  const sectors = new Set<string>();

  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_snapshot")
      .select("sector")
      .eq("run_date", runDate)
      .range(offset, offset + FETCH_CHUNK - 1);

    if (error || !data?.length) break;
    for (const row of data) {
      if (row.sector) sectors.add(row.sector as string);
    }
    if (data.length < FETCH_CHUNK) break;
  }

  return [...sectors].sort();
}

export type MoverBuckets = {
  observedOn: string | null;
  previousOn: string | null;
  climbers: MoverRow[];
  fallers: MoverRow[];
  upgrades: MoverRow[];
  downgrades: MoverRow[];
  entrants: MoverRow[];
};

const RATING_ORDER: Record<string, number> = {
  SELL: 0,
  REDUCE: 1,
  HOLD: 2,
  BUY: 3,
  "STRONG BUY": 4,
};

function ratingRank(rating: string | null): number | null {
  if (!rating) return null;
  const value = RATING_ORDER[rating.trim().toUpperCase()];
  return value === undefined ? null : value;
}

/**
 * Day-over-day movement, bucketed for display.
 *
 * The view already diffs against the previous *available* observation rather
 * than the previous calendar day, so a Monday is compared with Friday instead
 * of reporting the whole universe as new after every weekend.
 */
export async function getMovers(
  runDate: string,
  limit = 25,
): Promise<MoverBuckets> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_movers")
    .select("*")
    .eq("observed_on", runDate);

  if (error) {
    console.error("getMovers failed", error.message);
    return {
      observedOn: runDate,
      previousOn: null,
      climbers: [],
      fallers: [],
      upgrades: [],
      downgrades: [],
      entrants: [],
    };
  }

  const rows = (data ?? []) as MoverRow[];
  const previousOn =
    rows.find((row) => row.prev_observed_on)?.prev_observed_on ?? null;

  const ranked = rows.filter(
    (row) => row.rank_change !== null && !row.is_new_entrant,
  );

  const climbers = [...ranked]
    .filter((row) => (row.rank_change ?? 0) > 0)
    .sort((a, b) => (b.rank_change ?? 0) - (a.rank_change ?? 0))
    .slice(0, limit);

  const fallers = [...ranked]
    .filter((row) => (row.rank_change ?? 0) < 0)
    .sort((a, b) => (a.rank_change ?? 0) - (b.rank_change ?? 0))
    .slice(0, limit);

  const changed = rows.filter(
    (row) => row.rating_changed && row.prev_rating && !row.is_new_entrant,
  );

  const direction = (row: MoverRow) => {
    const now = ratingRank(row.rating);
    const before = ratingRank(row.prev_rating);
    if (now === null || before === null) return 0;
    return now - before;
  };

  const upgrades = changed
    .filter((row) => direction(row) > 0)
    .sort((a, b) => direction(b) - direction(a))
    .slice(0, limit);

  const downgrades = changed
    .filter((row) => direction(row) < 0)
    .sort((a, b) => direction(a) - direction(b))
    .slice(0, limit);

  const entrants = rows
    .filter((row) => row.is_new_entrant)
    .sort(
      (a, b) => (a.investment_rank ?? 1e9) - (b.investment_rank ?? 1e9),
    )
    .slice(0, limit);

  return {
    observedOn: runDate,
    previousOn,
    climbers,
    fallers,
    upgrades,
    downgrades,
    entrants,
  };
}

/** Full filtered result set for CSV export, paged past the PostgREST cap. */
export async function getExportRows(
  runDate: string,
  filters: ScreenerFilters,
  maxRows = 5000,
): Promise<SnapshotRow[]> {
  const rows: SnapshotRow[] = [];
  for (let page = 1; rows.length < maxRows; page += 1) {
    const { rows: chunk, total } = await getSnapshotPage(runDate, {
      ...filters,
      page,
    });
    rows.push(...chunk);
    if (!chunk.length || rows.length >= total) break;
  }
  return rows.slice(0, maxRows);
}
