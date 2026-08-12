/**
 * Display formatting.
 *
 * Two conventions are non-negotiable for this dataset:
 *
 *  - Indian digit grouping (12,34,567 not 1,234,567) and crore/lakh scaling,
 *    because the underlying figures are NSE rupee amounts and a reader
 *    comparing them against any Indian source would otherwise misread them by
 *    two orders of magnitude.
 *  - Missing is rendered as an explicit dash, never 0 or "-100%". The screener
 *    treats absent evidence as neutral, and a display that invents a value
 *    would contradict the model it is reporting.
 */

const EN_IN = "en-IN";

export const MISSING = "—"; // em dash

export function isMissing(value: unknown): value is null | undefined {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "number" && !Number.isFinite(value)) ||
    (typeof value === "string" && value.trim() === "")
  );
}

export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (isMissing(value)) return MISSING;
  return value.toLocaleString(EN_IN, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatInteger(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING;
  return Math.round(value).toLocaleString(EN_IN);
}

/** Rupee amount with Indian grouping. */
export function formatINR(
  value: number | null | undefined,
  digits = 2,
): string {
  if (isMissing(value)) return MISSING;
  return `₹${value.toLocaleString(EN_IN, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/**
 * Scale a rupee amount to crore/lakh. Market caps and turnover span nine orders
 * of magnitude across this universe, so a raw figure is unreadable in a column.
 */
export function formatINRCompact(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";

  if (abs >= 1e7) {
    return `${sign}₹${(abs / 1e7).toLocaleString(EN_IN, {
      maximumFractionDigits: abs / 1e7 >= 100 ? 0 : 1,
    })} Cr`;
  }
  if (abs >= 1e5) {
    return `${sign}₹${(abs / 1e5).toLocaleString(EN_IN, {
      maximumFractionDigits: 1,
    })} L`;
  }
  return `${sign}₹${abs.toLocaleString(EN_IN, {
    maximumFractionDigits: 0,
  })}`;
}

/** Value already expressed in percent (e.g. 12.5 renders as +12.5%). */
export function formatPercent(
  value: number | null | undefined,
  digits = 1,
  signed = false,
): string {
  if (isMissing(value)) return MISSING;
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString(EN_IN, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

/**
 * Value expressed as a ratio (0.125 renders as 12.5%).
 *
 * The screener exports both conventions -- ROE and growth arrive as ratios,
 * while Pct_Change_1M arrives already in percent -- so the call site must pick
 * the right helper. Mixing them is the single most likely display bug here.
 */
export function formatRatioAsPercent(
  value: number | null | undefined,
  digits = 1,
  signed = false,
): string {
  if (isMissing(value)) return MISSING;
  return formatPercent(value * 100, digits, signed);
}

export function formatScore(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING;
  return value.toFixed(1);
}

/** Coverage as a share of the fields the selected sector model expects. */
export function formatCoverage(
  present: number | null | undefined,
  expected: number | null | undefined,
): string {
  if (isMissing(present) || isMissing(expected) || expected === 0) {
    return MISSING;
  }
  return `${Math.round((present / expected) * 100)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (isMissing(value)) return MISSING;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return MISSING;
  return parsed.toLocaleDateString(EN_IN, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTimeIST(value: string | null | undefined): string {
  if (isMissing(value)) return MISSING;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return MISSING;
  return `${parsed.toLocaleString(EN_IN, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  })} IST`;
}

/** Whole-unit relative age, for the freshness banner. */
export function formatRelativeAge(value: string | null | undefined): string {
  if (isMissing(value)) return MISSING;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return MISSING;

  const minutes = Math.floor((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

export function ratingToken(rating: string | null | undefined): string {
  if (isMissing(rating)) return "hold";
  return rating.trim().toLowerCase().replace(/\s+/g, "-");
}

/** Number of trading-ish days old, used to decide the staleness banner level. */
export function daysSince(value: string | null | undefined): number | null {
  if (isMissing(value)) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return Math.floor((Date.now() - parsed.getTime()) / 86_400_000);
}
