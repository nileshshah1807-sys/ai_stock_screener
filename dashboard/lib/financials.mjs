/**
 * Financial statement tables for the stock page's Financials tab.
 *
 * The stored payload (see workers/financial_statements.py) carries reported
 * line items only. Everything a reader compares -- growth, margins, cash
 * conversion -- is derived here, at display time, and three rules govern it:
 *
 *  1. Periods are matched by DATE, never by column position. Yahoo skips
 *     quarters (TCS has no Sep 2025 column), so "the previous column" is not
 *     "the previous quarter": a positional QoQ would silently compare against
 *     a quarter six months back. QoQ looks for the quarter ending ~3 months
 *     earlier, YoY for the one ~12 months earlier.
 *
 *  2. A skipped quarter is drawn as a gap column, not closed up. Closing it
 *     would put Jun and Dec side by side and invite exactly the misreading
 *     rule 1 prevents.
 *
 *  3. Missing is missing. A growth rate needs both values reported and a
 *     positive base: growth off a loss ("-50 to +10 is +120%") is not a
 *     meaningful number, so it renders as a dash rather than a large green
 *     figure.
 */

const DAY = 86_400_000;
/** Quarter-end dates drift by a few days (Mar 31 vs Apr 1, 52-week years). */
const MATCH_TOLERANCE_DAYS = 20;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-06-30" -> "Jun 2026". */
export function periodLabel(iso) {
  const [year, month] = iso.split("-").map(Number);
  return `${MONTHS[month - 1]} ${year}`;
}

function toTime(iso) {
  return Date.parse(`${iso}T00:00:00Z`);
}

/** The ISO date `months` calendar months before `iso`, at month end. */
export function monthsBefore(iso, months) {
  const [year, month] = iso.split("-").map(Number);
  // Day 0 of the following month is the last day of the target month.
  const end = new Date(Date.UTC(year, month - months, 0));
  return end.toISOString().slice(0, 10);
}

/** Index of the period ending closest to `target`, within tolerance. */
export function findPeriod(periods, target) {
  const goal = toTime(target);
  let best = -1;
  let bestGap = Infinity;
  periods.forEach((period, index) => {
    const gap = Math.abs(toTime(period) - goal) / DAY;
    if (gap <= MATCH_TOLERANCE_DAYS && gap < bestGap) {
      best = index;
      bestGap = gap;
    }
  });
  return best;
}

/**
 * Display columns for a statement: every reported period, plus a gap column
 * for each quarter missing between the first and last (quarterly only).
 * Each column carries `source`, the index into the stored arrays, or null for
 * a gap.
 */
export function buildColumns(periods, { quarterly }) {
  if (!periods.length) return [];
  if (!quarterly) {
    return periods.map((period, source) => ({ period, label: periodLabel(period), source }));
  }
  const columns = [];
  let cursor = periods[0];
  const last = toTime(periods[periods.length - 1]);
  // Walk quarter by quarter; the guard stops a pathological payload looping.
  for (let guard = 0; guard < 200 && toTime(cursor) <= last + MATCH_TOLERANCE_DAYS * DAY; guard++) {
    const source = findPeriod(periods, cursor);
    const period = source >= 0 ? periods[source] : cursor;
    columns.push({ period, label: periodLabel(period), source: source >= 0 ? source : null });
    cursor = monthsBefore(period, -3);
  }
  return columns;
}

/** Percentage change, or null when it would not be meaningful. */
export function growth(current, base) {
  if (current == null || base == null || !Number.isFinite(current) || !Number.isFinite(base)) {
    return null;
  }
  if (base <= 0) return null;
  return ((current - base) / base) * 100;
}

/** `numerator / denominator` as a percentage, or null. */
export function ratio(numerator, denominator) {
  if (numerator == null || denominator == null || !denominator) return null;
  return (numerator / denominator) * 100;
}

/*
 * Row specs. `value` rows read a stored line; `growth` rows compare a line
 * against the period `months` earlier; `ratio` rows divide two lines, the
 * denominator optionally from another statement (CFO / PAT).
 */
const QUARTERLY = [
  { type: "value", key: "revenue", label: "Revenue", emphasis: true },
  { type: "growth", key: "revenue", months: 3, label: "Revenue QoQ" },
  { type: "growth", key: "revenue", months: 12, label: "Revenue YoY" },
  { type: "value", key: "net_interest_income", label: "Net interest income" },
  { type: "value", key: "expenses", label: "Expenses" },
  { type: "value", key: "operating_profit", label: "Operating profit", emphasis: true },
  { type: "ratio", num: "operating_profit", den: "revenue", label: "OPM" },
  { type: "value", key: "other_income", label: "Other income" },
  { type: "value", key: "interest", label: "Interest" },
  { type: "value", key: "depreciation", label: "Depreciation" },
  { type: "value", key: "pbt", label: "Profit before tax" },
  { type: "value", key: "tax", label: "Tax" },
  { type: "ratio", num: "tax", den: "pbt", label: "Tax rate" },
  { type: "value", key: "net_profit", label: "Net profit", emphasis: true },
  { type: "growth", key: "net_profit", months: 3, label: "Net profit QoQ" },
  { type: "growth", key: "net_profit", months: 12, label: "Net profit YoY" },
  { type: "ratio", num: "net_profit", den: "revenue", label: "NPM" },
  { type: "value", key: "eps", label: "EPS", perShare: true },
];

const PROFIT_LOSS = [
  { type: "value", key: "revenue", label: "Revenue", emphasis: true },
  { type: "growth", key: "revenue", months: 12, label: "Revenue growth" },
  { type: "value", key: "net_interest_income", label: "Net interest income" },
  { type: "value", key: "expenses", label: "Expenses" },
  { type: "value", key: "operating_profit", label: "Operating profit", emphasis: true },
  { type: "ratio", num: "operating_profit", den: "revenue", label: "OPM" },
  { type: "value", key: "other_income", label: "Other income" },
  { type: "value", key: "interest", label: "Interest" },
  { type: "value", key: "depreciation", label: "Depreciation" },
  { type: "value", key: "pbt", label: "Profit before tax" },
  { type: "value", key: "tax", label: "Tax" },
  { type: "ratio", num: "tax", den: "pbt", label: "Tax rate" },
  { type: "value", key: "net_profit", label: "Net profit", emphasis: true },
  { type: "growth", key: "net_profit", months: 12, label: "Net profit growth" },
  { type: "ratio", num: "net_profit", den: "revenue", label: "NPM" },
  { type: "value", key: "eps", label: "EPS", perShare: true },
  { type: "growth", key: "eps", months: 12, label: "EPS growth" },
];

const BALANCE_SHEET = [
  { type: "value", key: "equity_capital", label: "Equity capital" },
  { type: "value", key: "reserves", label: "Reserves" },
  { type: "value", key: "borrowings", label: "Borrowings" },
  { type: "value", key: "other_liabilities", label: "Other liabilities" },
  { type: "value", key: "total_assets", label: "Total liabilities", emphasis: true },
  { type: "value", key: "fixed_assets", label: "Fixed assets" },
  { type: "value", key: "cwip", label: "Capital work in progress" },
  { type: "value", key: "investments", label: "Investments" },
  { type: "value", key: "other_assets", label: "Other assets" },
  { type: "value", key: "total_assets", label: "Total assets", emphasis: true },
  { type: "value", key: "cash", label: "Cash & equivalents" },
  { type: "ratio", num: "borrowings", den: "shareholders_equity", label: "Debt / equity", asMultiple: true },
];

const CASH_FLOW = [
  { type: "value", key: "cfo", label: "Operating cash flow", emphasis: true },
  { type: "value", key: "cfi", label: "Investing cash flow" },
  { type: "value", key: "cff", label: "Financing cash flow" },
  { type: "value", key: "net_cash_flow", label: "Net cash flow", emphasis: true },
  { type: "value", key: "capex", label: "Capex" },
  { type: "value", key: "fcf", label: "Free cash flow", emphasis: true },
  { type: "ratio", num: "cfo", den: "net_profit", denFrom: "income", label: "CFO / net profit" },
];

export const VIEWS = {
  quarterly: { label: "Quarterly results", short: "Quarters", scope: "quarterly", statement: "income", rows: QUARTERLY },
  profit_loss: { label: "Profit & loss", short: "P&L", scope: "annual", statement: "income", rows: PROFIT_LOSS },
  balance_sheet: { label: "Balance sheet", short: "Balance", scope: "annual", statement: "balance", rows: BALANCE_SHEET },
  cash_flow: { label: "Cash flow", short: "Cash flow", scope: "annual", statement: "cashflow", rows: CASH_FLOW },
};

const EMPTY = { periods: [], rows: {} };

function statementOf(payload, scope, statement) {
  return payload?.[scope]?.[statement] ?? EMPTY;
}

/** Value of `key` in `statement` for the period nearest `iso`, or null. */
function valueAt(statement, key, iso) {
  const values = statement.rows?.[key];
  if (!values) return null;
  const index = findPeriod(statement.periods, iso);
  return index >= 0 ? (values[index] ?? null) : null;
}

/**
 * Build one view's table.
 *
 * Returns `{ columns, rows }`. Each row has `cells`, aligned to `columns`,
 * holding a number or null. Rows with no reported value in any column are
 * dropped, which is how a bank's statement loses the lines it does not file.
 */
export function buildView(payload, viewKey) {
  const view = VIEWS[viewKey];
  const statement = statementOf(payload, view.scope, view.statement);
  const columns = buildColumns(statement.periods, { quarterly: view.scope === "quarterly" });
  const other = view.rows.some((row) => row.denFrom)
    ? statementOf(payload, view.scope, view.rows.find((row) => row.denFrom).denFrom)
    : null;

  const rows = [];
  for (const spec of view.rows) {
    const cells = columns.map((column) => {
      if (column.source == null) return null;
      if (spec.type === "value") {
        return statement.rows?.[spec.key]?.[column.source] ?? null;
      }
      if (spec.type === "growth") {
        const current = statement.rows?.[spec.key]?.[column.source] ?? null;
        const base = valueAt(statement, spec.key, monthsBefore(column.period, spec.months));
        return growth(current, base);
      }
      const num = statement.rows?.[spec.num]?.[column.source] ?? null;
      const den = spec.denFrom
        ? valueAt(other, spec.den, column.period)
        : (statement.rows?.[spec.den]?.[column.source] ?? null);
      const value = ratio(num, den);
      if (value == null) return null;
      return spec.asMultiple ? value / 100 : value;
    });
    if (cells.some((cell) => cell != null)) {
      rows.push({ ...spec, id: `${spec.type}:${spec.label}`, cells });
    }
  }
  return { columns, rows };
}

/** Views that have at least one reported period, in display order. */
export function availableViews(payload) {
  return Object.keys(VIEWS).filter((key) => {
    const view = VIEWS[key];
    return statementOf(payload, view.scope, view.statement).periods.length > 0;
  });
}
