/**
 * Human labels for the screener's machine tokens.
 *
 * The export uses snake_case and SCREAMING_SNAKE status values. Rendering them
 * raw leaks implementation vocabulary into the interface, and worse, hides the
 * distinction that actually matters for most of them: whether the state is
 * *adverse evidence* or merely *absent evidence*. The model treats those very
 * differently, so each label ships with that meaning alongside it.
 */

type Explained = { label: string; meaning: string };

const DCF_STATUS: Record<string, Explained> = {
  OK: {
    label: "Usable",
    meaning:
      "Based on reported positive cash flow, so this result is blend-eligible and contributes to the score.",
  },
  estimated_fcf: {
    label: "Estimated cash flow",
    meaning:
      "Free cash flow was estimated rather than reported, so the result is neutral audit evidence and contributes zero.",
  },
  negative_fcf: {
    label: "Reported negative cash flow",
    meaning:
      "Kept distinct as unmodelled adverse cash-flow-quality evidence. It caps STRONG BUY by default rather than being scored.",
  },
  missing_or_negative_fcf: {
    label: "Missing or negative cash flow",
    meaning: "No usable positive cash flow to solve from. Contributes zero.",
  },
  sector_not_supported: {
    label: "Sector not supported",
    meaning:
      "Generic reverse DCF is disabled for this sector: the feed lacks bank regulatory and asset-quality inputs, and property-level NAV and project cash flows. Absence of a result is not a negative signal.",
  },
  missing_market_cap: {
    label: "Market cap unavailable",
    meaning: "Cannot compare implied value to market value. Contributes zero.",
  },
  low_fcf_yield: {
    label: "Cash-flow yield below floor",
    meaning:
      "The implied yield sits under the configured validity floor, so the solve is not trusted. Contributes zero.",
  },
  growth_above_model_range: {
    label: "Implied growth above model range",
    meaning:
      "The market is implying growth outside what this model will solve for. Reported rather than clamped to a false precision.",
  },
  growth_below_model_range: {
    label: "Implied growth below model range",
    meaning:
      "The market is implying growth outside what this model will solve for. Reported rather than clamped to a false precision.",
  },
};

const STABILITY_STATUS: Record<string, Explained> = {
  CLEAR: {
    label: "Clear",
    meaning: "Not close to any policy boundary.",
  },
  BORDERLINE: {
    label: "Borderline",
    meaning:
      "Close enough to a rating threshold that a small data revision could flip the label. Audit-only; it does not change the rating.",
  },
  POLICY_CAPPED: {
    label: "Policy capped",
    meaning: "A ceiling is holding this decision below its evidence score.",
  },
  DATA_LIMITED: {
    label: "Data limited",
    meaning:
      "Coverage is thin enough that the score rests on fewer inputs than the sector model expects.",
  },
};

const DATA_QUALITY: Record<string, Explained> = {
  FULL: { label: "Full", meaning: "All expected fields present." },
  LIMITED: {
    label: "Limited",
    meaning: "Some expected fields are missing; coverage gates may apply.",
  },
  LOW: {
    label: "Low",
    meaning: "Substantially incomplete. Cannot hold BUY conviction.",
  },
};

/**
 * Model 5.0 primary gate: the most severe reason a row is not rated higher.
 *
 * A BUY-eligible row can still report a gate here, because the question it
 * answers is "what is holding this back", not "why was this rejected".
 */
const PRIMARY_GATE: Record<string, Explained> = {
  NONE: { label: "None", meaning: "Clears every gate at its evidence score." },
  NO_SCORE: {
    label: "No core score",
    meaning: "Nothing to rank: the factor blend could not be computed.",
  },
  STALE_PRICE_BAR: {
    label: "Price bar behind session",
    meaning:
      "Measured on an older bar than the rest of the cross-section, so its trend and percentiles are not comparable today.",
  },
  STALE_FUNDAMENTALS: {
    label: "Stale fundamentals",
    meaning: "Retained from an expired cache as a fallback. Cannot hold BUY.",
  },
  LOW_DATA_QUALITY: {
    label: "Low data quality",
    meaning: "Substantially incomplete fundamentals.",
  },
  LOW_FACTOR_COVERAGE: {
    label: "Thin factor evidence",
    meaning:
      "At least one factor block was computed from too few observed inputs to be treated as evidence.",
  },
  LOW_COVERAGE: {
    label: "Coverage below floor",
    meaning:
      "Fundamental or technical coverage is under the Model 5.0 BUY minimum (0.70 / 0.90).",
  },
  SPECIALIST_MODEL_REQUIRED: {
    label: "Specialist model required",
    meaning:
      "A financial-sector row needs regulatory evidence the feed does not currently supply.",
  },
  DATA_ANOMALY: {
    label: "Data anomaly",
    meaning: "Two or more implausible fundamental values need validation.",
  },
  TREND_BREAKDOWN: {
    label: "Confirmed breakdown",
    meaning:
      "Persistently below a falling 200-day average with negative relative strength. The stricter exit condition, not a single dip.",
  },
  BELOW_MA200: {
    label: "Below 200-day average",
    meaning:
      "Outside the 2% tolerance band around its 200-day average. The band exists so a stock oscillating around the line does not flip rating daily.",
  },
  MA200_TREND: {
    label: "200-day trend",
    meaning: "The long-term average is unavailable or falling.",
  },
  WEAK_RELATIVE_STRENGTH: {
    label: "Weak relative strength",
    meaning: "Underperforming the benchmark or its sector over the window.",
  },
  LOW_QUALITY: {
    label: "Quality below floor",
    meaning:
      "Quality percentile is under the BUY (40) or STRONG BUY (70) floor for this cross-section.",
  },
  ILLIQUID: {
    label: "Insufficient liquidity",
    meaning:
      "Cannot be built at the configured position size, so it is research rather than an executable BUY.",
  },
  MARKET_REGIME: {
    label: "Market regime",
    meaning:
      "Broad-market conditions restrict conviction. Deployment only -- the research score is untouched.",
  },
  OTHER: { label: "Other", meaning: "See the full gate list." },
};

const MARKET_REGIME: Record<string, Explained> = {
  RISK_ON: {
    label: "Risk on",
    meaning: "Index above a rising long-term average. Normal policy applies.",
  },
  NEUTRAL: {
    label: "Neutral",
    meaning:
      "Index inside the band, or level and trend disagree. STRONG BUY needs exceptional momentum.",
  },
  RISK_OFF: {
    label: "Risk off",
    meaning:
      "Index below a falling long-term average. STRONG BUY is disabled and BUY requires top-decile momentum.",
  },
  UNKNOWN: {
    label: "Unknown",
    meaning: "Not enough benchmark history to classify. No overlay applied.",
  },
};

const ELIGIBILITY_CLASS: Record<string, Explained> = {
  "0": {
    label: "Clears every gate",
    meaning: "No policy ceiling applied at any level.",
  },
  "1": {
    label: "BUY eligible",
    meaning: "Passes every BUY gate but fails at least one STRONG BUY gate.",
  },
  "2": {
    label: "Policy capped",
    meaning:
      "Published, but a gate holds the decision below its evidence. Ordered within this class by research score.",
  },
  "3": {
    label: "Unscorable",
    meaning: "No decision score could be produced.",
  },
};

/** Fallback: turn any unknown token into readable text rather than showing it raw. */
function titleCase(token: string): string {
  const cleaned = token.replace(/[_-]+/g, " ").trim().toLowerCase();
  if (!cleaned) return "—";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function lookup(
  table: Record<string, Explained>,
  value: string | null | undefined,
): Explained {
  if (!value) return { label: "—", meaning: "" };
  const key = value.trim();
  return table[key] ?? { label: titleCase(key), meaning: "" };
}

export const dcfStatus = (value: string | null | undefined) =>
  lookup(DCF_STATUS, value);

export const stabilityStatus = (value: string | null | undefined) =>
  lookup(STABILITY_STATUS, value);

export const dataQuality = (value: string | null | undefined) =>
  lookup(DATA_QUALITY, value);

export const primaryGate = (value: string | null | undefined) =>
  lookup(PRIMARY_GATE, value);

export const marketRegime = (value: string | null | undefined) =>
  lookup(MARKET_REGIME, value);

export const eligibilityClass = (value: number | null | undefined) =>
  lookup(
    ELIGIBILITY_CLASS,
    value === null || value === undefined ? null : String(value),
  );

/** Generic humanizer for tokens with no curated entry. */
export const humanize = (value: string | null | undefined) =>
  value ? titleCase(value) : "—";
