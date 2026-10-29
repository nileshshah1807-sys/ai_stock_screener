/**
 * The Results page's arithmetic: which quarters it offers, and each card's
 * figures from the filings the exchange published.
 *
 * A card compares the quarter with the one before it (QoQ) and the same
 * quarter a year earlier (YoY), on one basis at a time -- consolidated and
 * standalone are different companies' worth of figures, and a growth rate
 * across the two would be meaningless. The rules are the stock page's
 * (`lib/financials.mjs`): a missing figure is a dash, and there is no growth
 * rate off a zero or negative base.
 */

import { GROWTH_METRICS, isGrowthRule } from "./event-filters.mjs";
import { growth, monthsBefore, periodLabel, ratio } from "./financials.mjs";

/** The lines a card shows, in the stock page's words. */
export const RESULT_LINES = [
  { key: "revenue", label: "Revenue" },
  // A bank's; a line no column has is left off, not shown as dashes.
  { key: "net_interest_income", label: "Net interest income", optional: true },
  // Margin rows open under the line they divide, as on the stock page.
  // Banks and insurers have none in this sense.
  { key: "operating_profit", label: "Operating profit", margin: { key: "opm", label: "OPM" }, optional: true },
  { key: "net_profit", label: "Net profit", margin: { key: "npm", label: "NPM" } },
  { key: "eps", label: "EPS", perShare: true },
];

/** How many quarters the picker offers: the exchange's index begins in April 2025. */
export const QUARTERS_OFFERED = 6;

/** The quarter ends on or before `today`, newest first. */
export function quarterEnds(today, count = QUARTERS_OFFERED) {
  const [year, month] = today.split("-").map(Number);
  // The end of the latest month divisible by three that has ended: this
  // month only on its last day.
  let end = monthsBefore(`${year}-${String(month).padStart(2, "0")}-01`, month % 3);
  if (end > today) end = monthsBefore(end, 3);
  const ends = [];
  for (let index = 0; index < count; index += 1) {
    ends.push(end);
    end = monthsBefore(end, 3);
  }
  return ends;
}

/**
 * "Sep 2026", with the Indian fiscal quarter for an Indian market: companies
 * there name a result by it ("Q2 FY27"), and a reader looks for that.
 */
export function quarterLabel(iso, { fiscal = false } = {}) {
  const label = periodLabel(iso);
  if (!fiscal) return label;
  const [year, month] = iso.split("-").map(Number);
  // The fiscal year runs April to March and is named by the year it ends in.
  const quarter = ((Math.floor((month - 1) / 3) + 3) % 4) + 1;
  const fiscalYear = month >= 4 ? year + 1 : year;
  return `${label} · Q${quarter} FY${String(fiscalYear).slice(-2)}`;
}

/** The quarter a URL asks for, if it is one the picker offers. */
export function chosenQuarter(value, offered) {
  const text = Array.isArray(value) ? value[0] : value;
  return typeof text === "string" && offered.includes(text) ? text : null;
}

/** Filings keyed by `period_end`, then by basis. */
function byPeriod(filings) {
  const periods = new Map();
  for (const filing of filings) {
    const key = filing.is_consolidated ? "consolidated" : "standalone";
    if (!periods.has(filing.period_end)) periods.set(filing.period_end, {});
    periods.get(filing.period_end)[key] = filing;
  }
  return periods;
}

function lineValue(filing, key) {
  const value = filing?.lines?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function marginValue(filing, key) {
  const numerator = key === "opm" ? "operating_profit" : "net_profit";
  return ratio(lineValue(filing, numerator), lineValue(filing, "revenue"));
}

/** Change in a margin, in percentage points; null unless both are known. */
function pointChange(current, base) {
  return current == null || base == null ? null : current - base;
}

/**
 * One basis of a card: the three quarters' figures and the two changes for
 * every line, or null when the company did not file this quarter on it.
 */
export function basisTable(filings, quarter, basis) {
  const periods = byPeriod(filings);
  const current = periods.get(quarter)?.[basis];
  if (!current) return null;
  const columns = [quarter, monthsBefore(quarter, 3), monthsBefore(quarter, 12)];
  const filed = columns.map((period) => periods.get(period)?.[basis] ?? null);

  const rows = RESULT_LINES.map((line) => {
    const values = filed.map((filing) => lineValue(filing, line.key));
    const row = {
      key: line.key,
      label: line.label,
      perShare: Boolean(line.perShare),
      values,
      yoy: growth(values[0], values[2]),
      qoq: growth(values[0], values[1]),
      margin: null,
    };
    if (line.margin) {
      const margins = filed.map((filing) => marginValue(filing, line.margin.key));
      row.margin = {
        key: line.margin.key,
        label: line.margin.label,
        values: margins,
        yoy: pointChange(margins[0], margins[2]),
        qoq: pointChange(margins[0], margins[1]),
      };
    }
    return row;
  }).filter((row, index) => !RESULT_LINES[index].optional || row.values.some((value) => value != null));

  return {
    basis,
    columns: columns.map((period) => ({ period, label: periodLabel(period) })),
    rows,
    filedAt: current.filed_at ?? null,
    documentUrl: current.viewer_url || current.document_url || null,
  };
}

/**
 * A company's card: a table per basis it filed this quarter on, consolidated
 * first -- the stock page's rule (`filed_statement` in
 * workers/financial_statements.py), since a group's consolidated figures are
 * the company an investor owns. A company that has only just begun to
 * consolidate opens on standalone, the basis its year-ago quarter is on.
 */
export function resultCard(entry, filings, quarter) {
  const bases = ["consolidated", "standalone"]
    .map((basis) => basisTable(filings, quarter, basis))
    .filter(Boolean);
  const yearAgo = byPeriod(filings).get(monthsBefore(quarter, 12)) ?? {};
  if (bases.length > 1 && !yearAgo.consolidated && yearAgo.standalone) bases.reverse();
  return { ...entry, bases };
}

/** Results grouped by the day, in the market's time, they were announced; order kept. */
export function groupByAnnouncedDay(entries, timeZone) {
  const day = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const groups = [];
  for (const entry of entries) {
    const date = entry.announced_at ? day.format(new Date(entry.announced_at)) : "";
    const last = groups[groups.length - 1];
    if (last && last.date === date) last.entries.push(entry);
    else groups.push({ date, entries: [entry] });
  }
  return groups;
}

/** A growth rate or change for a cell: always signed, so direction never rests on colour. */
export function formatChange(value, unit = "%") {
  if (value == null) return null;
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(1)}${unit}`;
}

/**
 * Decimals for a row of amounts, from its largest figure: the stock page's
 * rule, so a small company's quarter-to-quarter movement is not rounded away
 * and one row never mixes "42.0" with "1,568".
 */
export function amountDigits(values, divisor) {
  const largest = Math.max(0, ...values.map((value) => (value == null ? 0 : Math.abs(value / divisor))));
  if (largest >= 100) return 0;
  return largest >= 10 ? 1 : 2;
}

/**
 * Whether a card passes the growth rules among `rules`. The rate tested is the
 * one the card prints, on the basis it opens on (`bases[0]`); no rate -- a
 * loss for a base, a line the filing lacks -- passes no rule, as an unreported
 * figure passes none anywhere else on the filter bar.
 */
export function passesGrowth(card, rules) {
  return rules.filter(isGrowthRule).every((rule) => {
    const { line, period } = GROWTH_METRICS.find((item) => item.value === rule.metric).growth;
    const rate = card.bases[0]?.rows.find((row) => row.key === line)?.[period];
    if (typeof rate !== "number" || !Number.isFinite(rate)) return false;
    return rule.op === "gte" ? rate >= rule.value : rate <= rule.value;
  });
}
