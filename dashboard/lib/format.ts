/**
 * Display formatting.
 *
 * Two conventions are non-negotiable for this dataset:
 *
 *  - Money is grouped and scaled the way a reader of that market's own sources
 *    would expect: Indian grouping with crore/lakh for NSE rupee amounts
 *    (12,34,567 not 1,234,567), Western grouping with billions/millions for US
 *    dollar amounts. Using one convention for both misreads figures by two
 *    orders of magnitude.
 *  - Missing is rendered as an explicit dash, never 0 or "-100%". The screener
 *    treats absent evidence as neutral, and a display that invents a value
 *    would contradict the model it is reporting.
 */

import { DEFAULT_MARKET, type Market } from "@/lib/markets";

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

/** Money in a market's own currency and grouping. */
export function formatMoney(
  value: number | null | undefined,
  market: Market = DEFAULT_MARKET,
  digits = 2,
): string {
  if (isMissing(value)) return MISSING;
  return `${market.currencySymbol}${value.toLocaleString(market.locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/**
 * Scale a money amount to the market's own magnitude words.
 *
 * Market caps and turnover span nine orders of magnitude in either universe,
 * so a raw figure is unreadable in a column. The thresholds differ because the
 * words do: crore is 10^7 and lakh 10^5, against billion at 10^9 and million
 * at 10^6.
 */
export function formatMoneyCompact(
  value: number | null | undefined,
  market: Market = DEFAULT_MARKET,
): string {
  if (isMissing(value)) return MISSING;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const { currencySymbol, locale } = market;

  const steps =
    market.scale === "indian"
      ? ([
          [1e7, "Cr"],
          [1e5, "L"],
        ] as const)
      : ([
          [1e9, "B"],
          [1e6, "M"],
          [1e3, "K"],
        ] as const);

  for (const [divisor, unit] of steps) {
    if (abs >= divisor) {
      const scaled = abs / divisor;
      return `${sign}${currencySymbol}${scaled.toLocaleString(locale, {
        maximumFractionDigits: scaled >= 100 ? 0 : 1,
      })} ${unit}`;
    }
  }
  return `${sign}${currencySymbol}${abs.toLocaleString(locale, {
    maximumFractionDigits: 0,
  })}`;
}

/**
 * NSE-bound wrappers, kept so callers that have no market in scope keep
 * working unchanged. New code should pass a market to formatMoney instead.
 */
export function formatINR(
  value: number | null | undefined,
  digits = 2,
): string {
  return formatMoney(value, DEFAULT_MARKET, digits);
}

export function formatINRCompact(value: number | null | undefined): string {
  return formatMoneyCompact(value, DEFAULT_MARKET);
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
