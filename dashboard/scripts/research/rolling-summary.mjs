// Summarises out/rolling-filters.json and out/rolling-rules.json into
// out/rolling-summary.json, pairing every run with its comparison over the
// same window: a filter with the unfiltered ranking at the same settings, a
// rule combination with the same base and no rules.
//
//   node scripts/research/rolling-summary.mjs
import { readFileSync, writeFileSync } from "node:fs";

import { out } from "./paths.mjs";

const read = (name) => JSON.parse(readFileSync(out(name), "utf8"));
const quantile = (xs, q) => {
  const s = [...xs].sort((a, b) => a - b);
  if (!s.length) return null;
  const i = (s.length - 1) * q;
  const lo = Math.floor(i);
  return s[lo] + (s[Math.ceil(i)] - s[lo]) * (i - lo);
};
const share = (xs, test) => (xs.length ? (xs.filter(test).length / xs.length) * 100 : null);
const MARKETS = ["falling", "flat", "rising"];
const HORIZONS = ["6m", "1y", "3y"];

function describe(rows, pair) {
  return {
    runs: rows.length,
    windows: new Set(rows.map((r) => r.start)).size,
    medAnnual: quantile(rows.map((r) => r.annual), 0.5),
    p10Annual: quantile(rows.map((r) => r.annual), 0.1),
    medDD: quantile(rows.map((r) => r.dd), 0.5),
    worstDD: Math.min(...rows.map((r) => r.dd)),
    ddPast20: share(rows, (r) => r.dd < -20),
    beatNifty: share(rows, (r) => r.annual > r.bench.annual),
    medExcess: quantile(rows.map((r) => r.annual - r.bench.annual), 0.5),
    ...(pair && {
      beatPair: share(rows, (r) => r.annual > pair(r).annual),
      shallowerThanPair: share(rows, (r) => r.dd > pair(r).dd),
      medReturnVsPair: quantile(rows.map((r) => r.annual - pair(r).annual), 0.5),
      medDDVsPair: quantile(rows.map((r) => r.dd - pair(r).dd), 0.5),
    }),
  };
}

const summary = { filters: {}, rules: {}, markets: {} };

const f = read("rolling-filters.json");
summary.end = f.end;
const fkey = (r, pick) => [pick, r.topN, r.rebalance, r.weights, r.horizon, r.start].join("|");
const fIndex = new Map(f.rows.map((r) => [fkey(r, r.pick), r]));
const unfiltered = (r) => fIndex.get(fkey(r, "all"));
for (const h of HORIZONS) {
  const rows = f.rows.filter((r) => r.horizon === h);
  summary.filters[h] = {};
  for (const pick of [...new Set(rows.map((r) => r.pick))]) {
    const own = rows.filter((r) => r.pick === pick && unfiltered(r));
    summary.filters[h][pick] = {
      all: describe(own, pick === "all" ? null : unfiltered),
      byMarket: Object.fromEntries(MARKETS.map((m) => [m, describe(own.filter((r) => r.bench.market === m), pick === "all" ? null : unfiltered)])),
    };
  }
  // How many windows of each market type, counted once per start date.
  const starts = new Map(rows.filter((r) => r.pick === "all").map((r) => [r.start, r.bench.market]));
  summary.markets[h] = Object.fromEntries(MARKETS.map((m) => [m, [...starts.values()].filter((x) => x === m).length]));
}

// Reset to equal against hold as bought, same pick, size, frequency and window.
summary.weights = {};
for (const h of HORIZONS) {
  summary.weights[h] = {};
  for (const [scope, keep] of [["noFilter", (r) => r.pick === "all"], ["every", () => true]]) {
    const pairs = f.rows
      .filter((r) => r.weights === "equal" && r.horizon === h && keep(r))
      .map((e) => [e, fIndex.get([e.pick, e.topN, e.rebalance, "hold", h, e.start].join("|"))])
      .filter(([, hold]) => hold);
    summary.weights[h][scope] = {
      pairs: pairs.length,
      resetReturnedMore: share(pairs, ([e, hold]) => e.annual > hold.annual),
      medReturnDiff: quantile(pairs.map(([e, hold]) => e.annual - hold.annual), 0.5),
      resetShallower: share(pairs, ([e, hold]) => e.dd > hold.dd),
      medDDDiff: quantile(pairs.map(([e, hold]) => e.dd - hold.dd), 0.5),
    };
  }
}

const g = read("rolling-rules.json");
const gkey = (r, rules) => [r.base, rules, r.horizon, r.start].join("|");
const gIndex = new Map(g.rows.map((r) => [gkey(r, r.rules), r]));
const noRules = (r) => gIndex.get(gkey(r, "none"));
for (const h of HORIZONS) {
  const rows = g.rows.filter((r) => r.horizon === h);
  summary.rules[h] = {};
  for (const base of ["A", "B"]) {
    summary.rules[h][base] = {};
    for (const rules of [...new Set(rows.map((r) => r.rules))]) {
      const own = rows.filter((r) => r.base === base && r.rules === rules);
      summary.rules[h][base][rules] = {
        all: describe(own, rules === "none" ? null : noRules),
        byMarket: Object.fromEntries(MARKETS.map((m) => [m, describe(own.filter((r) => r.bench.market === m), rules === "none" ? null : noRules)])),
      };
    }
  }
}
writeFileSync(out("rolling-summary.json"), JSON.stringify(summary, null, 1));

const n = (x, d = 1) => (x == null ? "  —  " : x.toFixed(d).padStart(6));
for (const h of HORIZONS) {
  console.log(`\n== filters, ${h} (windows: ${JSON.stringify(summary.markets[h])}) ==`);
  console.log("pick                      runs medAnn  p10Ann  medDD  >-20%  beatNifty beatAll  shallower  retVsAll ddVsAll");
  for (const [pick, s] of Object.entries(summary.filters[h])) {
    const a = s.all;
    console.log(pick.padEnd(24), String(a.runs).padStart(5), n(a.medAnnual), n(a.p10Annual), n(a.medDD), n(a.ddPast20, 0), n(a.beatNifty, 0), n(a.beatPair, 0), n(a.shallowerThanPair, 0), n(a.medReturnVsPair), n(a.medDDVsPair));
  }
  console.log(`-- falling markets, ${h}`);
  for (const [pick, s] of Object.entries(summary.filters[h])) {
    const a = s.byMarket.falling;
    if (a.runs) console.log(pick.padEnd(24), String(a.runs).padStart(5), n(a.medAnnual), n(a.medDD), "beatAll", n(a.beatPair, 0), "shallower", n(a.shallowerThanPair, 0), "ddVsAll", n(a.medDDVsPair));
  }
}
for (const h of HORIZONS) {
  console.log(`\n== rules, ${h} ==`);
  for (const base of ["A", "B"]) for (const [rules, s] of Object.entries(summary.rules[h][base])) {
    const a = s.all, fall = s.byMarket.falling;
    console.log(base, rules.padEnd(9), "medAnn", n(a.medAnnual), "medDD", n(a.medDD), ">-20%", n(a.ddPast20, 0), "retVsNone", n(a.medReturnVsPair), "ddVsNone", n(a.medDDVsPair), "shallower", n(a.shallowerThanPair, 0), "| falling: ddVsNone", n(fall.medDDVsPair), "retVsNone", n(fall.medReturnVsPair), "n", fall.runs);
  }
}
