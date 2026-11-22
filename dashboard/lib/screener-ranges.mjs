// Every numeric screener filter, as data: one URL key each, `min~max` with
// either side optional (`pe=~25`, `cap=1000~`, `roe=15~30`). The panel, the
// active-filter chips and the query all read this list, so a filter added here
// appears everywhere at once.
//
// `scale` turns the number a viewer types into the column's own unit: ROE is
// stored as a fraction (0.15) and typed as a percent (15); debt to equity is
// stored as a percent (50) and typed as a multiple (0.5). `size` ranges are in
// the market's size unit (crore in India, millions in the US, SIZE_UNITS).

/**
 * @typedef {{ key: string, column: string, label: string, unit: string, scale?: number,
 *   size?: boolean, factor?: boolean, market?: string, direction?: boolean, legacyMin?: string,
 *   presets?: { label: string, min?: number, max?: number }[] }} RangeFilter
 */

// A `direction` range is only "went up" or "went down": no bounds to type. The column is stored to
// two decimals, so 0.01 is "above the earlier figure" and -0.01 "below it". The chip reads the words.
const direction = (/** @type {string} */ up, /** @type {string} */ down) => [{ label: up, min: 0.01 }, { label: down, max: -0.01 }];
const DIRECTION = direction("Increased", "Decreased");
const NET = direction("Net bought", "Net sold");

/** @type {{ id: string, label: string, ranges: RangeFilter[] }[]} */
export const RANGE_GROUPS = [
  {
    id: "size",
    label: "Size and liquidity",
    ranges: [
      {
        key: "cap",
        column: "market_cap",
        label: "Market cap",
        unit: "size",
        size: true,
        legacyMin: "minCapCr",
        presets: [
          { label: "≥ 20,000", min: 20000 },
          { label: "5,000–20,000", min: 5000, max: 20000 },
          { label: "500–5,000", min: 500, max: 5000 },
          { label: "< 500", max: 500 },
        ],
      },
      {
        key: "turnover",
        column: "median_turnover_20d_inr",
        label: "Daily turnover (20-day median)",
        unit: "size",
        size: true,
        presets: [
          { label: "≥ 1", min: 1 },
          { label: "≥ 10", min: 10 },
        ],
      },
    ],
  },
  {
    id: "valuation",
    label: "Valuation",
    ranges: [
      { key: "pe", column: "pe_ratio", label: "P/E", unit: "×", presets: [{ label: "0–15", min: 0, max: 15 }, { label: "0–25", min: 0, max: 25 }, { label: "> 50", min: 50 }] },
      { key: "pb", column: "pb_ratio", label: "P/B", unit: "×", presets: [{ label: "< 1", max: 1 }, { label: "< 3", max: 3 }] },
      { key: "evebitda", column: "ev_ebitda", label: "EV/EBITDA", unit: "×", presets: [{ label: "0–10", min: 0, max: 10 }, { label: "0–20", min: 0, max: 20 }] },
      { key: "ps", column: "ps_ratio", label: "Price to sales", unit: "×", presets: [{ label: "< 1", max: 1 }, { label: "< 3", max: 3 }] },
      { key: "dy", column: "dividend_yield", label: "Dividend yield", unit: "%", presets: [{ label: "≥ 1", min: 1 }, { label: "≥ 3", min: 3 }] },
    ],
  },
  {
    id: "quality",
    label: "Profitability and debt",
    ranges: [
      { key: "roe", column: "roe", label: "Return on equity", unit: "%", scale: 0.01, presets: [{ label: "≥ 15", min: 15 }, { label: "≥ 25", min: 25 }] },
      { key: "roic", column: "roic", label: "Return on capital", unit: "%", scale: 0.01, presets: [{ label: "≥ 15", min: 15 }] },
      { key: "de", column: "debt_to_equity", label: "Debt to equity", unit: "×", scale: 100, presets: [{ label: "< 0.5", max: 0.5 }, { label: "< 1", max: 1 }] },
      // The latest filed quarter (NSE filings, screener/quarterly_results.py), in percent, and its move
      // from the same quarter a year earlier in points.
      { key: "opm", column: "opm_latest_q_pct", label: "Operating margin, latest quarter", unit: "%", market: "NSE", presets: [{ label: "≥ 15", min: 15 }, { label: "≥ 25", min: 25 }] },
      { key: "opmch", column: "opm_change_yoy_pp", label: "Operating margin vs same quarter last year", unit: "pp", market: "NSE", direction: true, presets: direction("Expanded", "Contracted") },
    ],
  },
  {
    id: "growth",
    label: "Growth",
    ranges: [
      { key: "revg", column: "revenue_growth", label: "Revenue growth, year on year", unit: "%", scale: 0.01, presets: [{ label: "≥ 15", min: 15 }, { label: "≥ 30", min: 30 }] },
      { key: "epsg", column: "earnings_growth", label: "Profit growth, year on year", unit: "%", scale: 0.01, presets: [{ label: "≥ 15", min: 15 }, { label: "≥ 30", min: 30 }] },
    ],
  },
  {
    id: "returns",
    label: "Price returns",
    ranges: [
      { key: "r1d", column: "pct_change_1d", label: "1 day", unit: "%" },
      { key: "r1m", column: "pct_change_1m", label: "1 month", unit: "%", presets: [{ label: "> 0", min: 0 }, { label: "≥ 10", min: 10 }] },
      { key: "r3m", column: "pct_change_3m", label: "3 months", unit: "%", presets: [{ label: "> 0", min: 0 }, { label: "≥ 20", min: 20 }] },
      { key: "r6m", column: "pct_change_6m", label: "6 months", unit: "%", presets: [{ label: "> 0", min: 0 }] },
      { key: "r12m", column: "pct_change_12m", label: "12 months", unit: "%", presets: [{ label: "> 0", min: 0 }, { label: "≥ 50", min: 50 }] },
      { key: "hi52", column: "pct_from_52w_high", label: "From 52-week high", unit: "%", presets: [{ label: "Within 5", min: -5 }, { label: "Within 15", min: -15 }, { label: "30 or more", max: -30 }] },
    ],
  },
  {
    id: "technical",
    label: "Technical",
    ranges: [
      { key: "rs", column: "rs_rating", label: "RS rating", unit: "", factor: true, legacyMin: "minRs", presets: [{ label: "≥ 70", min: 70 }, { label: "≥ 90", min: 90 }] },
      { key: "rsi", column: "rsi_14", label: "RSI (14)", unit: "", presets: [{ label: "< 30", max: 30 }, { label: "> 70", min: 70 }] },
      { key: "vol", column: "volatility_ann_pct", label: "Volatility, annualised", unit: "%", presets: [{ label: "< 30", max: 30 }, { label: "< 45", max: 45 }] },
      { key: "dd", column: "max_drawdown_1y_pct", label: "Worst fall in a year", unit: "%", presets: [{ label: "Under 20", min: -20 }, { label: "Under 35", min: -35 }] },
    ],
  },
  {
    id: "factors",
    label: "Factor percentiles",
    ranges: [
      { key: "pq", column: "quality_percentile", label: "Quality", unit: "P", factor: true, legacyMin: "minQuality", presets: [{ label: "≥ 70", min: 70 }, { label: "≥ 90", min: 90 }] },
      { key: "pg", column: "growth_percentile", label: "Growth", unit: "P", factor: true, presets: [{ label: "≥ 70", min: 70 }] },
      { key: "pm", column: "momentum_percentile", label: "Momentum", unit: "P", factor: true, legacyMin: "minMomentum", presets: [{ label: "≥ 70", min: 70 }, { label: "≥ 90", min: 90 }] },
      { key: "pv", column: "value_percentile", label: "Value", unit: "P", factor: true, presets: [{ label: "≥ 70", min: 70 }] },
      { key: "pr", column: "risk_percentile", label: "Steadiness", unit: "P", factor: true, presets: [{ label: "≥ 70", min: 70 }] },
    ],
  },
  {
    // Stamped on each NSE row by workers/ownership_flows.py: the latest shareholding pattern, its move
    // from the quarter before in percentage points, and the sector's FPI net in NSDL's latest
    // fortnight less its six-month average, in crore.
    id: "ownership",
    label: "Ownership and flows",
    ranges: [
      { key: "promoter", column: "promoter_pct", label: "Promoter holding", unit: "%", market: "NSE", presets: [{ label: "≥ 50", min: 50 }, { label: "≥ 70", min: 70 }] },
      { key: "fii", column: "fii_pct", label: "FII holding", unit: "%", market: "NSE", presets: [{ label: "≥ 10", min: 10 }, { label: "≥ 20", min: 20 }, { label: "< 2", max: 2 }] },
      { key: "dii", column: "dii_pct", label: "DII holding", unit: "%", market: "NSE", presets: [{ label: "≥ 10", min: 10 }, { label: "≥ 20", min: 20 }] },
      { key: "promoterch", column: "promoter_change_qoq", label: "Promoter holding vs previous quarter", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "fiich", column: "fii_change_qoq", label: "FII holding vs previous quarter", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "diich", column: "dii_change_qoq", label: "DII holding vs previous quarter", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "retail", column: "retail_pct", label: "Retail holding", unit: "%", market: "NSE", presets: [{ label: "< 20", max: 20 }, { label: "≥ 40", min: 40 }] },
      { key: "promoter1y", column: "promoter_change_1y", label: "Promoter holding vs a year ago", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "fii1y", column: "fii_change_1y", label: "FII holding vs a year ago", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "dii1y", column: "dii_change_1y", label: "DII holding vs a year ago", unit: "pp", market: "NSE", direction: true, presets: DIRECTION },
      { key: "sfpi", column: "sector_fpi_vs_avg_cr", label: "Sector FPI flow vs 6-month average", unit: "Cr", market: "NSE", presets: [{ label: "Above average", min: 0 }, { label: "Below average", max: 0 }] },
      // Bulk and block deals in the last 30 days, bought less sold, crore; null where there were none.
      { key: "deals", column: "deals_net_cr_1m", label: "Bulk/block deals, last month", unit: "Cr", market: "NSE", direction: true, presets: NET },
      { key: "fdeals", column: "foreign_deals_net_cr_1m", label: "Foreign funds' deals, last month", unit: "Cr", market: "NSE", direction: true, presets: NET },
    ],
  },
  {
    // workers/results_timing.py: from the latest quarter's announcement, and to the announced date.
    id: "results",
    label: "Results",
    ranges: [
      { key: "dsr", column: "days_since_result", label: "Days since results", unit: "days", presets: [{ label: "Last 7 days", max: 7 }, { label: "Last 30 days", max: 30 }] },
      { key: "dtr", column: "days_to_result", label: "Days to results", unit: "days", presets: [{ label: "Next 7 days", min: 0, max: 7 }, { label: "Next 14 days", min: 0, max: 14 }] },
    ],
  },
];

/**
 * Whether the filter panel offers a range: factor ranges on a factor-model run only, and a
 * market's own evidence (shareholding, FPI flows) in that market only.
 * @param {RangeFilter} range
 * @param {{ market: string, factorModel: boolean }} context
 */
export function rangeShown(range, { market, factorModel }) {
  return (factorModel || !range.factor) && (!range.market || range.market === market);
}

export const RANGES = RANGE_GROUPS.flatMap((group) => group.ranges);

/** Every URL key a range filter answers to, the old single-bound keys included. */
export const RANGE_KEYS = RANGES.flatMap((range) => (range.legacyMin ? [range.key, range.legacyMin] : [range.key]));

/** @param {string | null | undefined} text */
const bound = (text) => {
  if (text === undefined || text === null || text.trim() === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) ? value : undefined;
};

/**
 * `"10~25"` -> { min: 10, max: 25 }; either side may be empty. Null when neither bound is a number.
 * @param {string | null | undefined} text
 * @returns {{ min?: number, max?: number } | null}
 */
export function parseRange(text) {
  if (!text) return null;
  const [low, high] = String(text).split("~");
  const min = bound(low);
  const max = high === undefined ? undefined : bound(high);
  if (min === undefined && max === undefined) return null;
  return { ...(min === undefined ? {} : { min }), ...(max === undefined ? {} : { max }) };
}

/**
 * The URL form of a range, or "" when it bounds nothing.
 * @param {{ min?: number, max?: number }} range
 */
export function formatRange({ min, max }) {
  if (min === undefined && max === undefined) return "";
  return `${min ?? ""}~${max ?? ""}`;
}

/**
 * Every range set in `params` (URLSearchParams or a plain record), keyed by filter key.
 * An old single-bound key (`minCapCr=1000`) reads as that filter's minimum.
 * @param {(key: string) => string | null | undefined} get
 * @returns {Record<string, { min?: number, max?: number }>}
 */
export function readRanges(get) {
  /** @type {Record<string, { min?: number, max?: number }>} */
  const out = {};
  for (const range of RANGES) {
    const parsed = parseRange(get(range.key));
    const legacy = range.legacyMin ? bound(get(range.legacyMin)) : undefined;
    if (parsed) out[range.key] = parsed;
    else if (legacy !== undefined) out[range.key] = { min: legacy };
  }
  return out;
}

/**
 * The column bounds a range sets, in the column's own unit.
 * @param {RangeFilter} range
 * @param {{ min?: number, max?: number }} value
 * @param {number} sizeFactor currency units per size unit (1e7 for crore)
 */
export function columnBounds(range, value, sizeFactor) {
  const scale = range.size ? sizeFactor : (range.scale ?? 1);
  return {
    min: value.min === undefined ? undefined : value.min * scale,
    max: value.max === undefined ? undefined : value.max * scale,
  };
}

/**
 * A chip's text: "P/E 0–25", "Market cap ≥ 1,000 Cr", "Return on equity ≤ 30%".
 * @param {RangeFilter} range
 * @param {{ min?: number, max?: number }} value
 * @param {string} sizeSuffix "Cr" or "M"
 */
export function rangeLabel(range, value, sizeSuffix) {
  if (range.direction) {
    const up = value.min !== undefined && value.min > 0;
    const word = up || (value.max !== undefined && value.max < 0) ? range.presets?.[up ? 0 : 1]?.label : undefined;
    if (word) return `${range.label}: ${word}`;
  }
  // A word unit takes a space ("0.5 pp", "0 Cr"); a sign does not ("15%").
  const unit = range.size ? ` ${sizeSuffix}` : range.unit === "P" || range.unit === "" ? "" : /^[a-z]/i.test(range.unit) ? ` ${range.unit}` : range.unit;
  const show = (/** @type {number} */ n) => `${range.unit === "P" ? "P" : ""}${n.toLocaleString("en-IN")}${unit}`;
  if (value.min !== undefined && value.max !== undefined) return `${range.label} ${show(value.min)}–${show(value.max)}`;
  if (value.min !== undefined) return `${range.label} ≥ ${show(value.min)}`;
  return `${range.label} ≤ ${show(/** @type {number} */ (value.max))}`;
}
