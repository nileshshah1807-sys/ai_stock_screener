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
 *   size?: boolean, factor?: boolean, legacyMin?: string,
 *   presets?: { label: string, min?: number, max?: number }[] }} RangeFilter
 */

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
      { key: "pr", column: "risk_percentile", label: "Risk (higher is calmer)", unit: "P", factor: true, presets: [{ label: "≥ 70", min: 70 }] },
    ],
  },
];

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
  const unit = range.size ? ` ${sizeSuffix}` : range.unit === "P" || range.unit === "" ? "" : range.unit;
  const show = (/** @type {number} */ n) => `${range.unit === "P" ? "P" : ""}${n.toLocaleString("en-IN")}${unit}`;
  if (value.min !== undefined && value.max !== undefined) return `${range.label} ${show(value.min)}–${show(value.max)}`;
  if (value.min !== undefined) return `${range.label} ≥ ${show(value.min)}`;
  return `${range.label} ≤ ${show(/** @type {number} */ (value.max))}`;
}
