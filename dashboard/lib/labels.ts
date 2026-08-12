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

/** Generic humanizer for tokens with no curated entry. */
export const humanize = (value: string | null | undefined) =>
  value ? titleCase(value) : "—";
