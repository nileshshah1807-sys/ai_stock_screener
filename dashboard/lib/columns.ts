/**
 * The screener grid's column registry.
 *
 * Columns used to be declared twice in `screener-table.tsx` -- once as header
 * cells, once as body cells -- so adding or moving one was a two-place edit
 * that silently misaligned the grid if you got it wrong. They are declared
 * once here instead, and the table maps over this list for both rows.
 *
 * Deliberately free of JSX so `lib/queries.ts` can import it on the server to
 * build the Supabase projection. The matching cell renderers live beside the
 * table in `screener-table.tsx`, keyed by the same `id`.
 */

export type ColumnId =
  | "rank"
  | "stock"
  | "score"
  | "quality"
  | "momentum"
  | "growth"
  | "fundamental"
  | "technical"
  | "rating"
  | "coverage"
  | "dcf"
  | "evidence"
  | "price"
  | "change1d"
  | "change1m"
  | "marketCap"
  | "pe"
  | "liq";

/**
 * Which model's run a column belongs to.
 *
 * A run is either 4.x or Model 5.0 for its whole cross-section, so showing
 * both sets would double the grid width and leave whichever model did not run
 * as a full column of dashes.
 */
export type ColumnAvailability = "always" | "factor" | "legacy";

export type ColumnSpec = {
  id: ColumnId;
  label: string;
  /** Header `title`, shown as the native tooltip. */
  title?: string;
  /** Right-aligned, for figures that should share a decimal position. */
  numeric?: boolean;
  /** Snapshot column to sort on. Omitted for columns with no single sort key. */
  sort?: string;
  defaultDir?: "asc" | "desc";
  headerClassName?: string;
  /** Cell classes other than padding, which the renderer applies per density. */
  cellClassName?: string;
  /**
   * Snapshot columns this cell reads.
   *
   * The projection is assembled from these, so a cell that reads a field not
   * listed here renders as missing rather than throwing -- which is the failure
   * mode to watch for when adding a column.
   */
  fields: readonly string[];
  /** Excluded from the visibility control: the grid is meaningless without it. */
  required?: boolean;
  availability?: ColumnAvailability;
};

/**
 * Columns needed regardless of what is visible.
 *
 * `factor_model_applied` decides which of the two column sets renders, and
 * `symbol` is the row key and the drill-down href, so neither can be dropped
 * by hiding a column.
 */
export const BASE_FIELDS: readonly string[] = [
  "run_date",
  "symbol",
  "factor_model_applied",
];

export const COLUMNS: readonly ColumnSpec[] = [
  {
    id: "rank",
    label: "#",
    sort: "investment_rank",
    defaultDir: "asc",
    numeric: true,
    headerClassName: "w-12",
    cellClassName: "tabular text-right font-mono text-xs text-muted-foreground",
    title:
      "Investment Rank: decision score first, then evidence. The primary rank.",
    fields: ["investment_rank"],
    required: true,
  },
  {
    id: "stock",
    label: "Stock",
    headerClassName: "sticky-col",
    cellClassName: "sticky-col",
    fields: ["company", "logo_domain"],
    required: true,
  },
  {
    id: "score",
    label: "Score",
    sort: "final_score",
    numeric: true,
    title:
      "Published score: the uncapped research evidence. Policy gates limit the rating, not this number.",
    // Pinned beside Stock. Scrolling right to reach PE and Liq used to carry
    // the reader away from the one number the whole page is about.
    headerClassName: "sticky-col-2",
    cellClassName: "sticky-col-2 text-right",
    fields: [
      "final_score",
      "evidence_score",
      "decision_score",
      "rating",
      "policy_eligible_rating",
      "decision_cap_reason",
      "rating_cap_reason",
    ],
    required: true,
  },
  {
    id: "quality",
    label: "Qual",
    sort: "quality_percentile",
    numeric: true,
    cellClassName: "text-right",
    title:
      "Quality percentile: ROIC, cash generation, accruals, leverage and stability, ranked within sector. BUY needs 40, STRONG BUY 70.",
    fields: ["quality_percentile"],
    availability: "factor",
  },
  {
    id: "momentum",
    label: "Mom",
    sort: "momentum_percentile",
    numeric: true,
    cellClassName: "text-right",
    title:
      "Momentum percentile: risk-adjusted 12-1 and 6-1 returns plus relative strength. STRONG BUY needs 70.",
    fields: ["momentum_percentile"],
    availability: "factor",
  },
  {
    id: "growth",
    label: "Grow",
    sort: "growth_percentile",
    numeric: true,
    cellClassName: "text-right",
    title:
      "Growth percentile: multi-year CAGR, acceleration, margin direction and cash confirmation. STRONG BUY needs 60.",
    fields: ["growth_percentile"],
    availability: "factor",
  },
  {
    id: "fundamental",
    label: "Fund",
    sort: "fundamental_score",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    fields: ["fundamental_score"],
    availability: "legacy",
  },
  {
    id: "technical",
    label: "Tech",
    sort: "technical_score",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    fields: ["technical_score"],
    availability: "legacy",
  },
  {
    // After the factor block, not before the score. The score and its three
    // block percentiles answer "how strong is this?" and belong together; the
    // rating answers the separate question of whether policy will act on it,
    // and reads as a conclusion drawn from the columns to its left.
    id: "rating",
    label: "Rating",
    fields: [
      "rating",
      "rating_capped",
      "decision_cap_reason",
      "rating_cap_reason",
      "primary_gate",
      // Feeds the entry chip's distance-to-clearing text: "2.3% below 200DMA"
      // says what would have to change, where a bare gate name does not.
      "price_to_ma200_pct",
    ],
  },
  {
    id: "coverage",
    label: "Cov F/T",
    numeric: true,
    cellClassName: "text-right",
    title:
      "Fundamental coverage as a share of the fields the selected sector model expects, and technical score coverage.",
    fields: ["fundamental_coverage", "technical_coverage"],
  },
  {
    id: "dcf",
    label: "DCF",
    sort: "dcf_base_case_upside",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    title: "Reverse-DCF base-case upside. Evidence only; not a target price.",
    fields: ["dcf_status", "dcf_base_case_upside"],
  },
  {
    id: "evidence",
    label: "Evidence",
    title: "Transcript, red-flag, and rating-cap indicators",
    fields: [
      "transcript_status",
      "transcript_scoring_eligible",
      "transcript_guidance",
      "red_flag_status",
      "red_flag_severity",
      "shadow_red_flag_would_change",
      "rating_capped",
      "rating_cap_reason",
      "decision_cap_reason",
      // The capped chip distinguishes "a gate fired" from "a gate moved the
      // score", which needs the published score and the ceiling together.
      "final_score",
      "evidence_score",
      "decision_score",
    ],
  },
  {
    id: "price",
    label: "Price",
    sort: "current_price",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    fields: ["current_price"],
  },
  {
    // Between Price and 1M, so the return columns read shortest-to-longest
    // horizon left to right.
    id: "change1d",
    label: "1D",
    sort: "pct_change_1d",
    numeric: true,
    cellClassName: "text-right font-mono text-xs",
    title:
      "Last completed session's move, on the same adjusted close every technical feature uses. Display evidence: no score, gate or rank reads it.",
    fields: ["pct_change_1d"],
  },
  {
    id: "change1m",
    label: "1M",
    sort: "pct_change_1m",
    numeric: true,
    cellClassName: "text-right font-mono text-xs",
    fields: ["pct_change_1m"],
  },
  {
    id: "marketCap",
    label: "Mkt cap",
    sort: "market_cap",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    fields: ["market_cap"],
  },
  {
    id: "pe",
    label: "PE",
    sort: "pe_ratio",
    numeric: true,
    cellClassName: "tabular text-right font-mono text-xs",
    fields: ["pe_ratio"],
  },
  {
    id: "liq",
    label: "Liq",
    title: "Execution overlay. Never changes the score or rating.",
    fields: [
      "liquidity_grade",
      "portfolio_actionable",
      "median_turnover_20d_inr",
    ],
  },
];

const BY_ID = new Map(COLUMNS.map((column) => [column.id, column]));

/** Columns the visibility control may switch off. */
export const HIDEABLE_COLUMNS = COLUMNS.filter((column) => !column.required);

export type Density = "compact" | "comfortable";

/**
 * Read the hidden-column list out of a URL parameter.
 *
 * Stored as the *hidden* set rather than the visible one so that adding a
 * column later shows up for everyone by default instead of being invisible to
 * anyone holding an older link.
 *
 * Unknown ids are dropped rather than preserved: they would otherwise
 * accumulate in shared URLs and make the parameter unreadable. Required
 * columns are dropped too, so a hand-edited URL cannot produce a grid with no
 * ticker in it.
 */
export function parseHiddenColumns(raw: string | undefined): ColumnId[] {
  if (!raw) return [];
  const seen = new Set<ColumnId>();
  for (const token of raw.split(",")) {
    const id = token.trim() as ColumnId;
    const column = BY_ID.get(id);
    if (column && !column.required) seen.add(id);
  }
  return [...seen];
}

export function serializeHiddenColumns(hidden: Iterable<ColumnId>): string {
  // Registry order rather than click order, so two people who hid the same
  // columns produce the same URL and the same cache key.
  const set = new Set(hidden);
  return COLUMNS.filter((column) => set.has(column.id))
    .map((column) => column.id)
    .join(",");
}

export function parseDensity(raw: string | undefined): Density {
  return raw === "comfortable" ? "comfortable" : "compact";
}

/**
 * Columns to render, in order, for one run and one hidden set.
 *
 * `factorModel` null means the run predates the flag; both sets are then
 * offered to the caller, which matches how the table probed the rows before
 * this registry existed.
 */
export function visibleColumns(
  hidden: readonly ColumnId[],
  factorModel: boolean,
): ColumnSpec[] {
  const hiddenSet = new Set(hidden);
  return COLUMNS.filter((column) => {
    if (hiddenSet.has(column.id)) return false;
    const availability = column.availability ?? "always";
    if (availability === "factor") return factorModel;
    if (availability === "legacy") return !factorModel;
    return true;
  });
}

/**
 * Supabase projection for a hidden set.
 *
 * Deliberately ignores `factor_model_applied`: the projection is built on the
 * server before any row has been read, and asking the database which model ran
 * before asking it for the rows would add a round trip to save four null
 * columns. Hiding a column is what actually narrows this, and that is where
 * the payload win lives -- measured against this database, 100 rows of 61
 * columns is 155 KB and 301 ms while ~34 columns is 66 KB and 171 ms.
 *
 * Sorting is unaffected by what is selected: `.order()` runs in Postgres, so a
 * sortable column need not appear here.
 */
export function gridProjection(hidden: readonly ColumnId[]): string {
  const hiddenSet = new Set(hidden);
  const fields = new Set<string>(BASE_FIELDS);
  for (const column of COLUMNS) {
    if (hiddenSet.has(column.id)) continue;
    for (const field of column.fields) fields.add(field);
  }
  return [...fields].join(",");
}
