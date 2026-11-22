/**
 * The Flows page's FPI figures, from the R2 object workers/fpi_flows.py writes
 * (`live/NSE/fpi-flows.json`): `rows`, one per NSDL fortnight
 * `{ period_start, period_end, sectors: [{ sector, net, held }], total: { net, held } }`,
 * rupees crore; and `deals`, `{ bought, sold }` of foreign clients' net deals per
 * stock over the 30 days from `deals_since`. Kept free of React so `node --test`
 * can exercise it. Display only: nothing scores on it.
 */

/** Fortnights in the history grid (six months), and in the one-year total. */
export const HISTORY = 12;
export const YEAR = 24;

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const num = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
const sum = (values) => {
  const present = values.filter((value) => value !== null);
  return present.length ? present.reduce((a, b) => a + b, 0) : null;
};

/** "1–15 Nov 2026" for a fortnight's first and last day. */
export function fortnightLabel(start, end) {
  if (!ISO.test(start ?? "") || !ISO.test(end ?? "")) return "—";
  const [year, month, last] = end.split("-").map(Number);
  return `${Number(start.slice(8))}–${last} ${MONTHS[month - 1]} ${year}`;
}

/** A fortnight's month, for the grid's axis: "Nov". */
export function fortnightMonth(end) {
  return ISO.test(end ?? "") ? MONTHS[Number(end.slice(5, 7)) - 1] : "";
}

/**
 * The sector table: the latest fortnight's net and holdings per sector, its
 * last HISTORY fortnights' nets (null where a report lacked the sector) and the
 * sum over the last YEAR fortnights, largest net buying first; the same for all
 * sectors together. A sector holding nothing and bought nothing in the latest
 * report (NSDL's "Sovereign" row) is left out. null when there are no fortnights.
 */
export function sectorFlows(rows, { history = HISTORY, year = YEAR } = {}) {
  const periods = (Array.isArray(rows) ? rows : [])
    .filter((row) => ISO.test(row?.period_end ?? "") && Array.isArray(row?.sectors))
    .map((row) => ({ ...row, bySector: new Map(row.sectors.map((s) => [s?.sector, s])) }))
    .sort((a, b) => (a.period_end < b.period_end ? -1 : 1));
  const latest = periods.at(-1);
  if (!latest) return null;
  const shown = periods.slice(-history);
  const lastYear = periods.slice(-year);
  const netOf = (period, name) => num(period.bySector.get(name)?.net);

  const sectors = latest.sectors
    .filter((s) => typeof s?.sector === "string" && (num(s.held) || num(s.net)))
    .map((s) => ({
      sector: s.sector,
      net: num(s.net),
      held: num(s.held),
      history: shown.map((period) => netOf(period, s.sector)),
      year: sum(lastYear.map((period) => netOf(period, s.sector))),
    }))
    .sort((a, b) => (b.net ?? -Infinity) - (a.net ?? -Infinity));

  return {
    latest: { start: latest.period_start, end: latest.period_end },
    periods: shown.map((period) => ({ start: period.period_start, end: period.period_end })),
    yearSpan: lastYear.length,
    sectors,
    total: {
      sector: "All sectors",
      net: num(latest.total?.net),
      held: num(latest.total?.held),
      history: shown.map((period) => num(period.total?.net)),
      year: sum(lastYear.map((period) => num(period.total?.net))),
    },
  };
}

/** The largest absolute sector net in the grid: the scale every cell and bar is drawn against. */
export function gridScale(table) {
  const values = (table?.sectors ?? []).flatMap((s) => [s.net, ...s.history]).filter((v) => v !== null);
  return Math.max(1, ...values.map(Math.abs));
}

/**
 * A grid cell's fill: buying green, selling red, the strength by the square
 * root of its share of the scale so a modest fortnight still shows; a missing
 * figure gets no fill.
 */
export function heatFill(net, scale) {
  if (net === null || net === undefined || !Number.isFinite(net)) return "transparent";
  const share = Math.round(Math.sqrt(Math.min(1, Math.abs(net) / Math.max(1, scale))) * 72);
  return `color-mix(in oklab, ${net >= 0 ? "var(--positive)" : "var(--negative)"} ${share}%, var(--control))`;
}

/** The object's foreign deals: `{ bought, sold, since }`, each side kept to rows with a symbol and a net. */
export function foreignDeals(body) {
  const side = (rows) =>
    (Array.isArray(rows) ? rows : []).filter((d) => typeof d?.symbol === "string" && num(d?.net) !== null);
  return {
    bought: side(body?.deals?.bought),
    sold: side(body?.deals?.sold),
    since: ISO.test(body?.deals_since ?? "") ? body.deals_since : null,
  };
}
