import "server-only";

import { cache } from "react";

import { gridProjection } from "@/lib/columns";
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

/**
 * Chunk offsets for a universe-wide read, given a known row count.
 *
 * The run manifest already carries `row_count`, so the number of chunks is
 * known before the first request. That lets a full-universe read issue its
 * chunks concurrently instead of discovering the end by walking them one at a
 * time -- three sequential round trips become one round trip's worth of wall
 * clock. Callers without a count fall back to the sequential walk.
 */
function chunkOffsets(rowCount: number): number[] {
  const chunks = Math.max(1, Math.ceil(rowCount / FETCH_CHUNK));
  return Array.from({ length: chunks }, (_, index) => index * FETCH_CHUNK);
}

/**
 * Columns the on-screen grid renders, when nothing is hidden.
 *
 * Derived from the column registry rather than listed here, so a column and the
 * fields it reads are declared in one place and cannot drift apart -- the way
 * `pb_ratio` and `roe` once did in the export, where the column map named them
 * but the select did not and they were written empty for every row.
 *
 * This read is payload-bound rather than latency-bound: measured against this
 * database, 100 rows of 61 columns is 155 KB and 301 ms, while the same 100
 * rows of the ~34 columns the grid actually displays is 66 KB and 171 ms --
 * within noise of the 167 ms network round trip. Every unused column is pure
 * transfer cost on every sort, filter and page change, which is why hiding a
 * column narrows this select instead of only hiding cells in the browser.
 *
 * Sorting is unaffected by what is selected: `.order()` runs in Postgres, so a
 * sortable column need not appear here. The CSV export needs a different and
 * partly wider set, which is why EXPORT_COLUMNS exists separately.
 */
const GRID_COLUMNS = gridProjection([]);

/**
 * Columns the CSV export writes.
 *
 * A superset of the grid in places and a subset in others, so it is listed
 * independently. `pb_ratio` and `roe` appear in the export's own column map but
 * were missing from the single shared select, which meant those two columns
 * were written empty for every row -- selecting them here is what fixes that.
 */
const EXPORT_COLUMNS = [
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
  "pct_change_1d",
  "pct_change_1m",
  "pct_change_3m",
  "market_cap",
  "pe_ratio",
  // Written by the export's column map but previously never selected, so these
  // two were emitted empty for every row.
  "pb_ratio",
  "roe",
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
  // Model 5.0. Null on 4.x rows; the export writes them regardless so a
  // downstream consumer can tell which model scored the run.
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
  "pct_change_1d",
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

/**
 * Run manifest columns, minus `manifest` itself.
 *
 * That one jsonb column is 7.1 KB of an 8.2 KB row and nothing in the dashboard
 * reads it -- it is an archival record of the run, kept for forensics against
 * the database rather than for display. Selecting it cost 256 ms against 172 ms
 * for the same row without it, on every page load, because this read sits on the
 * critical path in the app layout.
 *
 * Listed explicitly rather than filtered client-side because PostgREST has no
 * "everything except" syntax. A new run column must be added here to reach the
 * dashboard, which is the cost of the 84 ms.
 */
const RUN_COLUMNS = [
  "run_date",
  "generated_at_utc",
  "price_bar_as_of",
  "analysis_as_of",
  "row_count",
  "model_version",
  "recommendation_policy_version",
  "output_schema_version",
  "model_validation_status",
  "config_sha256",
  "git_sha",
  "git_dirty",
  "market_calendar_version",
  "universe_selected_count",
  "technical_requested_count",
  "technical_collected_count",
  "technical_failed_count",
  "fundamental_missing_count",
  "strong_buy_count",
  "buy_count",
  "hold_count",
  "reduce_count",
  "sell_count",
  "sectors",
  "factor_model_applied",
  "ingested_at",
].join(",");

/**
 * Wrapped in React's cache() so the shell layout, the screener layout and the
 * page itself share one round trip rather than asking three times per render.
 */
export const getLatestRun = cache(async (): Promise<ScreenerRun | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_runs")
    .select(RUN_COLUMNS)
    // The publisher reserves a run_date with row_count=0 before writing its
    // dependent rows, then replaces this with the completed manifest. Never
    // let an in-flight or abandoned reservation displace the last good run.
    .gt("row_count", 0)
    .order("run_date", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    console.error("getLatestRun failed", error.message);
    return null;
  }
  return data as unknown as ScreenerRun | null;
});

export async function getRecentRuns(limit = 30): Promise<ScreenerRun[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_runs")
    // Same exclusion as getLatestRun, and it matters more here: 30 runs of the
    // 7.1 KB manifest is ~213 KB transferred to render a list of dates.
    .select(RUN_COLUMNS)
    .gt("row_count", 0)
    .order("run_date", { ascending: false })
    .limit(limit);

  if (error) {
    console.error("getRecentRuns failed", error.message);
    return [];
  }
  // Double cast, as in getSnapshotPage: a runtime column string gives
  // PostgREST's generic no shape to infer, so it widens to GenericStringError[].
  return (data ?? []) as unknown as ScreenerRun[];
}

/**
 * Filtered, sorted, paginated grid read.
 *
 * Filtering runs in Postgres rather than the browser so the page weight stays
 * constant as the universe grows, and so a filter reflects the whole universe
 * rather than whatever subset happened to be loaded.
 *
 * The projection follows the caller's hidden-column set, so hiding columns is a
 * transfer saving on every subsequent sort, filter and page change rather than
 * only a visual one. An explicit `columns` option still wins, which is how the
 * export asks for its own wider set.
 *
 * `symbols` restricts the read to an explicit set, which is what lets the
 * watchlist page reuse this function whole rather than growing a parallel query
 * that would have to re-implement the projection, the sort whitelist, all
 * fourteen filters and the pagination -- and then drift from them.
 */
export async function getSnapshotPage(
  runDate: string,
  filters: ScreenerFilters,
  options: { columns?: string; symbols?: readonly string[] } = {},
): Promise<{ rows: SnapshotRow[]; total: number }> {
  const supabase = await createClient();
  const projection =
    options.columns ??
    (filters.hiddenColumns?.length
      ? gridProjection(filters.hiddenColumns)
      : GRID_COLUMNS);

  let query = supabase
    .from("screener_snapshot")
    .select(projection, { count: "exact" })
    .eq("run_date", runDate);

  if (options.symbols) {
    // An empty restriction means "nothing", never "everything". Falling through
    // to an unrestricted read would show an empty watchlist the entire
    // universe, which is the worst possible failure for this feature.
    if (!options.symbols.length) return { rows: [], total: 0 };
    // PostgREST expresses this as `symbol=in.(A,B,C)` in the query string, so
    // the set size is bounded by URL length. WATCHLIST_MAX_SYMBOLS keeps it
    // inside a couple of kilobytes.
    query = query.in("symbol", [...options.symbols]);
  }

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
  // Filter on the number the table displays. Since Model 5.1 that is the
  // uncapped published score; filtering on the capped decision_score would
  // silently exclude rows whose visible score is inside the requested range.
  if (typeof filters.minScore === "number") {
    query = query.gte("final_score", filters.minScore);
  }
  if (typeof filters.maxScore === "number") {
    query = query.lte("final_score", filters.maxScore);
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
export const getSearchIndex = cache(
  async (runDate: string, rowCount?: number): Promise<SearchEntry[]> => {
    const supabase = await createClient();
    const select = "symbol, company, investment_rank, rating, final_score";
    const toEntry = (row: Record<string, unknown>): SearchEntry => ({
      s: row.symbol as string,
      c: (row.company as string) ?? "",
      r: row.investment_rank as number | null,
      g: row.rating as string | null,
      d: row.final_score as number | null,
    });

    const chunk = (offset: number) =>
      supabase
        .from("screener_snapshot")
        .select(select)
        .eq("run_date", runDate)
        .order("investment_rank", { ascending: true, nullsFirst: false })
        .range(offset, offset + FETCH_CHUNK - 1);

    if (rowCount && rowCount > 0) {
      const results = await Promise.all(chunkOffsets(rowCount).map(chunk));
      const entries: SearchEntry[] = [];
      for (const { data, error } of results) {
        if (error) {
          console.error("getSearchIndex failed", error.message);
          continue;
        }
        for (const row of data ?? []) entries.push(toEntry(row));
      }
      return entries;
    }

    const entries: SearchEntry[] = [];
    for (let offset = 0; ; offset += FETCH_CHUNK) {
      const { data, error } = await chunk(offset);
      if (error) {
        console.error("getSearchIndex failed", error.message);
        break;
      }
      if (!data?.length) break;
      for (const row of data) entries.push(toEntry(row));
      if (data.length < FETCH_CHUNK) break;
    }
    return entries;
  },
);

/**
 * Did this run score with the Model 5.0 factor architecture?
 *
 * Asked of the run rather than of the current page, because the page is
 * already filtered: a filter that returns no rows would otherwise hide the
 * factor columns and controls exactly when the user is trying to adjust them.
 * A run is entirely one model or the other, so one row settles it.
 */
export const runUsesFactorModel = cache(async (runDate: string): Promise<boolean> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_snapshot")
    .select("symbol")
    .eq("run_date", runDate)
    .eq("factor_model_applied", true)
    .limit(1);

  if (error) {
    // A pre-migration database has no such column. Falling back to "4.x" keeps
    // the dashboard working instead of failing the whole page render.
    console.error("runUsesFactorModel failed", error.message);
    return false;
  }
  return (data?.length ?? 0) > 0;
});

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

/**
 * The encoded daily price series for one symbol, plus the shared calendar.
 *
 * Two reads rather than a join: the calendar is one row shared by every symbol
 * and is `cache()`d per request, so a page that renders several charts pays for
 * it once. PostgREST cannot express "give me this series and that singleton" in
 * one round trip anyway.
 *
 * Returns null rather than throwing when the tables do not exist yet, so a
 * deployment that has not run the price-series migration renders the rest of
 * the stock page normally.
 */
export const getPriceCalendar = cache(async (): Promise<string[] | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("price_calendar")
    .select("sessions")
    .eq("id", 1)
    .maybeSingle();

  if (error) {
    console.error("getPriceCalendar failed", error.message);
    return null;
  }
  if (!data?.sessions) return null;
  try {
    return JSON.parse(data.sessions as string) as string[];
  } catch {
    console.error("getPriceCalendar: sessions is not valid JSON");
    return null;
  }
});

export type PriceSeriesRow = {
  session_deltas: string;
  closes: string;
  volumes: string;
  points: number;
  first_session: string;
  last_session: string;
};

export async function getPriceSeries(
  symbol: string,
): Promise<PriceSeriesRow | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("price_series")
    .select("session_deltas, closes, volumes, points, first_session, last_session")
    .eq("symbol", symbol.toUpperCase())
    .maybeSingle();

  if (error) {
    console.error("getPriceSeries failed", error.message);
    return null;
  }
  return (data as PriceSeriesRow | null) ?? null;
}

/**
 * Sessions observed after the published series ends.
 *
 * The base series is rebuilt from the archive only periodically, because it is
 * back-adjusted -- a new split has to restate every historical price, which an
 * append cannot do. Between rebuilds the daily run is already writing a row per
 * symbol into `screener_history`, so the chart reads that tail rather than
 * going stale.
 *
 * These closes are unadjusted, which is correct until the next corporate
 * action: they are on the same scale as the adjusted base right up to the
 * moment a split happens, after which a rebuild restates both.
 */
export async function getPriceTail(
  symbol: string,
  after: string,
): Promise<{ time: string; close: number; volume: number }[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("screener_history")
    .select("observed_on, current_price, volume")
    .eq("symbol", symbol.toUpperCase())
    .gt("observed_on", after)
    .order("observed_on", { ascending: true });

  if (error) {
    // A stale tail is a far smaller problem than a blank stock page.
    console.error("getPriceTail failed", error.message);
    return [];
  }
  return (data ?? [])
    .filter((row) => row.current_price !== null && Number(row.current_price) > 0)
    .map((row) => ({
      time: row.observed_on as string,
      close: Number(row.current_price),
      volume: row.volume === null ? 0 : Number(row.volume),
    }));
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

/**
 * Distinct sectors in a run.
 *
 * PostgREST has no DISTINCT, so this still reads one column across the whole
 * universe to collapse ~2,400 rows into ~11 values. Passing the manifest's
 * row count lets the chunks go out concurrently, and the result is invariant
 * per run, so the screener layout fetches it once rather than once per sort.
 */
export const getSectors = cache(
  async (runDate: string, rowCount?: number): Promise<string[]> => {
    const supabase = await createClient();
    const sectors = new Set<string>();

    const chunk = (offset: number) =>
      supabase
        .from("screener_snapshot")
        .select("sector")
        .eq("run_date", runDate)
        .range(offset, offset + FETCH_CHUNK - 1);

    if (rowCount && rowCount > 0) {
      const results = await Promise.all(chunkOffsets(rowCount).map(chunk));
      for (const { data, error } of results) {
        if (error) {
          console.error("getSectors failed", error.message);
          continue;
        }
        for (const row of data ?? []) {
          if (row.sector) sectors.add(row.sector as string);
        }
      }
      return [...sectors].sort();
    }

    for (let offset = 0; ; offset += FETCH_CHUNK) {
      const { data, error } = await chunk(offset);
      if (error || !data?.length) break;
      for (const row of data) {
        if (row.sector) sectors.add(row.sector as string);
      }
      if (data.length < FETCH_CHUNK) break;
    }

    return [...sectors].sort();
  },
);

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

export type PriceMoverRow = {
  symbol: string;
  company: string | null;
  investment_rank: number | null;
  rating: string | null;
  current_price: number | null;
  pct_change_1d: number | null;
};

const PRICE_MOVER_COLUMNS =
  "symbol, company, investment_rank, rating, current_price, pct_change_1d";

/**
 * Biggest single-session gainers and losers.
 *
 * Reads `screener_snapshot` rather than the `screener_movers` view, for two
 * reasons. The view diffs `screener_history.current_price`, which is the *raw*
 * close, so a split or a large dividend would publish a fabricated -90% mover;
 * `pct_change_1d` is computed on adjusted closes by the model itself. And a
 * snapshot read needs no previous run, so these two panels work on a first-ever
 * publication, where every rank and rating bucket is necessarily empty.
 *
 * Two ordered reads rather than one full-universe read and a client-side sort:
 * Postgres already has the index, and the whole point is to move ~2,400 rows of
 * transfer off the wire for the 15 rows actually rendered.
 */
export async function getPriceMovers(
  runDate: string,
  limit = 15,
): Promise<{ gainers: PriceMoverRow[]; losers: PriceMoverRow[] }> {
  const supabase = await createClient();

  const side = (ascending: boolean) =>
    supabase
      .from("screener_snapshot")
      .select(PRICE_MOVER_COLUMNS)
      .eq("run_date", runDate)
      // Runs published before Pct_Change_1D existed carry null for every row.
      // Excluding them here is what lets the page decide to render nothing at
      // all rather than two panels of dashes presented as the day's movers.
      .not("pct_change_1d", "is", null)
      .order("pct_change_1d", { ascending, nullsFirst: false })
      .order("symbol", { ascending: true })
      .limit(limit);

  const [top, bottom] = await Promise.all([side(false), side(true)]);

  if (top.error || bottom.error) {
    console.error(
      "getPriceMovers failed",
      top.error?.message ?? bottom.error?.message,
    );
    return { gainers: [], losers: [] };
  }

  const rows = (result: { data: unknown }) =>
    ((result.data ?? []) as unknown as PriceMoverRow[]).filter(
      (row) => row.pct_change_1d !== null,
    );

  return {
    // A flat session is neither a gain nor a fall. Without this a universe that
    // barely moved fills both panels with +0.00% rows.
    gainers: rows(top).filter((row) => (row.pct_change_1d ?? 0) > 0),
    losers: rows(bottom).filter((row) => (row.pct_change_1d ?? 0) < 0),
  };
}

/**
 * Full filtered result set for CSV export, paged past the PostgREST cap.
 *
 * Selects EXPORT_COLUMNS rather than the grid's leaner set: a download is not
 * latency-sensitive and is expected to carry every field the CSV declares.
 */
export async function getExportRows(
  runDate: string,
  filters: ScreenerFilters,
  maxRows = 5000,
): Promise<SnapshotRow[]> {
  const rows: SnapshotRow[] = [];
  for (let page = 1; rows.length < maxRows; page += 1) {
    const { rows: chunk, total } = await getSnapshotPage(
      runDate,
      { ...filters, page },
      { columns: EXPORT_COLUMNS },
    );
    rows.push(...chunk);
    if (!chunk.length || rows.length >= total) break;
  }
  return rows.slice(0, maxRows);
}
