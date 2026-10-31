// The stock page's Shareholding tab, as tables built from the stored filings
// (storage/shareholding_schema.sql). Pure, so it is tested with node --test.

import { monthsBefore, periodLabel } from "./financials.mjs";

export const GROUPS = [
  { key: "promoter", label: "Promoter" },
  { key: "fii", label: "FII" },
  { key: "dii", label: "DII" },
  { key: "public", label: "Public" },
];

/** Quarters shown, latest last: the last ten, like every results site. */
export const QUARTERS_SHOWN = 10;

// Two places: adding or subtracting two-place stakes in floating point
// otherwise prints 0.23000000000000398.
function round2(value) {
  return Math.round(value * 100) / 100;
}

/**
 * Promoter, FII, DII and public by quarter, and each one's change in
 * percentage points over the last quarter and the last year.
 *
 * QoQ and YoY are measured against the filing a quarter and four quarters
 * before the latest *by date*, so a quarter a company did not file leaves a
 * blank rather than comparing with the wrong one.
 */
export function buildPattern(patterns) {
  const sorted = [...(patterns ?? [])].sort((a, b) => a.period_end.localeCompare(b.period_end));
  const shown = sorted.slice(-QUARTERS_SHOWN);
  const byPeriod = new Map(sorted.map((row) => [row.period_end, row]));
  const latest = shown.at(-1);
  const prior = (months) => (latest ? byPeriod.get(monthsBefore(latest.period_end, months)) : null);
  const quarterAgo = prior(3);
  const yearAgo = prior(12);

  const delta = (key, row) =>
    latest && row && latest[key] != null && row[key] != null
      ? round2(latest[key] - row[key])
      : null;

  return {
    columns: shown.map((row) => ({ period: row.period_end, label: periodLabel(row.period_end) })),
    rows: [
      ...GROUPS.map(({ key, label }) => ({
        key,
        label,
        percent: true,
        cells: shown.map((row) => numberOrNull(row[key])),
        qoq: delta(key, quarterAgo),
        yoy: delta(key, yearAgo),
        lowerIsBetter: key === "public",
      })),
      {
        key: "shareholders",
        label: "No. of shareholders",
        percent: false,
        lowerIsBetter: true,
        cells: shown.map((row) => numberOrNull(row.shareholders)),
        qoq: delta("shareholders", quarterAgo),
        yoy: delta("shareholders", yearAgo),
      },
    ],
  };
}

/**
 * Named holders by quarter, for the given groups, largest in the latest
 * quarter first. A holder is matched across quarters by name, ignoring case
 * and spacing: filings spell the same fund "ICICI PRUDENTIAL" one quarter and
 * "ICICI Prudential" the next. A quarter the holder is not named in is blank
 * -- under the 1% a public holder must be named at, or gone. A holder with no
 * stake in any shown quarter is left out.
 */
export function buildHolders(patterns, groups) {
  const sorted = [...(patterns ?? [])]
    .sort((a, b) => a.period_end.localeCompare(b.period_end))
    .slice(-QUARTERS_SHOWN);
  const wanted = new Set(groups);
  const holders = new Map();
  sorted.forEach((row, column) => {
    for (const holder of row.holders ?? []) {
      if (!wanted.has(holder.group)) continue;
      const key = `${holder.group}:${holder.name.toLowerCase().replace(/\s+/g, " ").trim()}`;
      let entry = holders.get(key);
      if (!entry) {
        entry = { key, name: holder.name, group: holder.group, cells: sorted.map(() => null) };
        holders.set(key, entry);
      }
      // Two rows of one holder in one filing (a fund named in two tables) add up.
      entry.cells[column] = round2((entry.cells[column] ?? 0) + holder.pct);
      entry.name = holder.name;
    }
  });
  // Since June 2025 a filing lists every promoter-group entity, most of them at
  // 0.00% (Tata Sons' group: ~300). Such a holder has nothing to show, and its
  // rows would make every earlier quarter's column read blank.
  const rows = [...holders.values()]
    .filter((entry) => entry.cells.some((pct) => pct))
    .sort(
      (a, b) => (b.cells.at(-1) ?? -1) - (a.cells.at(-1) ?? -1) || maxOf(b.cells) - maxOf(a.cells),
    );
  return {
    columns: sorted.map((row) => ({ period: row.period_end, label: periodLabel(row.period_end) })),
    rows,
  };
}

function maxOf(cells) {
  return Math.max(-1, ...cells.filter((value) => value != null));
}

function numberOrNull(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
