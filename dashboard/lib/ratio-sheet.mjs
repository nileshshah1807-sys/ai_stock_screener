/**
 * The stock page's ratio sheet: one price ratio taken apart into its inputs,
 * against its own history and its industry. Reads the object
 * `ratio-sheet/{MARKET}/{SYMBOL}.json` (spec: hive/agents/pam-mvnswinr/specs/
 * ratio-sheet-object.md) and the live price; the ratio itself is worked out by
 * live-compute's `valuation`, the same rule as the tile, so the two never differ.
 * Display only, no rating: it reaches every viewer.
 */
import { valuation } from "./live-compute.mjs";
import { median } from "./results.mjs";

/** The sheet's metrics: the tile's key, the history/peer field, and its name. */
export const RATIO_SHEETS = {
  pe_ratio: { field: "pe", name: "P/E" },
  pb_ratio: { field: "pb", name: "P/B" },
  ev_ebitda: { field: "ev_ebitda", name: "EV/EBITDA" },
  market_cap: { field: "market_cap", name: "Market cap" },
};

const num = (value) => (value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value));
const per = (top, bottom) => (top === null || bottom === null || bottom === 0 ? null : top / bottom);

/**
 * The ratio at `price` and the steps that make it: each { label, value, unit }
 * where unit is "price" (per share, in money), "money" (a total) or "multiple".
 * `changePct` null means a withheld change of unit: no ratio, as the tile.
 */
export function ratioInputs(metric, price, changePct, basis) {
  const at = valuation({ price, change_pct: changePct }, basis ?? {});
  const shares = num(basis?.shares_outstanding);
  const marketCap = at.market_cap;
  const step = (label, value, unit) => ({ label, value, unit });
  const head = [step("Price", num(price), "price"), step("Shares outstanding", shares, "count"), step("Market cap", marketCap, "money")];
  if (metric === "market_cap") return { value: marketCap, steps: head };
  if (metric === "pe_ratio") {
    const profit = num(basis?.net_profit_ttm);
    return { value: at.pe_ratio, steps: [...head, step("Trailing net profit", profit, "money"), step("Earnings per share", per(profit, shares), "price")] };
  }
  if (metric === "pb_ratio") {
    const book = num(basis?.book_equity);
    return { value: at.pb_ratio, steps: [...head, step("Book equity", book, "money"), step("Book value per share", per(book, shares), "price")] };
  }
  const debt = num(basis?.total_debt);
  const cash = num(basis?.total_cash);
  const ev = marketCap === null || debt === null || cash === null ? null : marketCap + debt - cash;
  return {
    value: at.ev_ebitda,
    steps: [...head, step("Debt", debt, "money"), step("Cash", cash, "money"), step("Enterprise value", ev, "money"), step("Trailing EBITDA", num(basis?.ebitda_ttm), "money")],
  };
}

/**
 * The metric's quarter-end history, oldest first, its median over the points that
 * have a value, and where `current` sits against it (0.1 = 10% above). A median
 * at or below zero has no meaningful "above" and gives null.
 */
export function ratioHistory(history, metric, current) {
  const field = RATIO_SHEETS[metric]?.field;
  const points = (history ?? []).map((point) => ({ period_end: point.period_end, value: num(point[field]) }));
  const mid = median(points.map((p) => p.value).filter((v) => v !== null));
  const vsMedian = mid === null || mid <= 0 || current === null ? null : current / mid - 1;
  return { points, median: mid, vsMedian };
}

/** The peers' values for the metric, highest market cap first, and their median. */
export function peerComparison(peers, metric) {
  const field = RATIO_SHEETS[metric]?.field;
  const rows = [...(peers?.rows ?? [])]
    .sort((a, b) => (num(b.market_cap) ?? -Infinity) - (num(a.market_cap) ?? -Infinity))
    .map((row) => ({ symbol: row.symbol, company: row.company ?? row.symbol, value: num(row[field]) }));
  return { industry: peers?.industry ?? null, rows, median: median(rows.map((r) => r.value).filter((v) => v !== null)) };
}

/** Where the inputs come from, in words: four filed quarters, or the vendor's figures. */
export function basisSource(basis) {
  if (!basis) return null;
  const quarters = basis.quarters ?? [];
  const statement = basis.statement_basis ? `, ${basis.statement_basis}` : "";
  return basis.source === "filings" && quarters.length
    ? `Trailing ${quarters.length} filed quarters to ${quarters.at(-1)}${statement}`
    : `Latest reported figures${basis.period_end ? ` to ${basis.period_end}` : ""}${statement}`;
}
