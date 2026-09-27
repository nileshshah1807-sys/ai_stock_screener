// Rolling windows: a fresh basket started every month, held 6 months, 1 year
// or 3 years, for every filter setting (part "filters") or every P7 rule
// combination (part "rules"). One row per window per setting, into
// out/rolling-<part>.json; rolling-report.mjs summarises them.
//
//   node scripts/research/rolling.mjs filters|rules [2026-08-10]
//
// Market type is fixed here, before any result: the Nifty 500's yearly
// return over the window below 0% is falling, 0-10% flat, above 10% rising.
import { writeFileSync } from "node:fs";

import { benchmarkCurve, loadData, metrics, PICKS, run, runRules } from "./engine.mjs";
import { out } from "./paths.mjs";

const [part = "filters", end = "2026-08-10"] = process.argv.slice(2);
const data = loadData(end);
const HORIZONS = [
  { name: "6m", months: 6 },
  { name: "1y", months: 12 },
  { name: "3y", months: 36 },
];
const plusMonths = (date, months) => {
  const t = new Date(`${date}T00:00:00Z`);
  t.setUTCMonth(t.getUTCMonth() + months);
  return t.toISOString().slice(0, 10);
};
const lastSessionOnOrBefore = (date) => {
  let found = null;
  for (const s of data.sessions) {
    if (s > date) break;
    found = s;
  }
  return found;
};
// The first ranking of each month, from `from`.
const monthStarts = (from) => {
  const seen = new Set();
  return data.dates.filter((d) => {
    if (d < from || seen.has(d.slice(0, 7))) return false;
    seen.add(d.slice(0, 7));
    return true;
  });
};
const marketType = (annualPct) => (annualPct < 0 ? "falling" : annualPct <= 10 ? "flat" : "rising");

function windowsFrom(from) {
  const windows = [];
  for (const h of HORIZONS) {
    for (const start of monthStarts(from)) {
      const stop = plusMonths(start, h.months);
      if (stop > data.asOf) continue;
      const asOf = lastSessionOnOrBefore(stop);
      windows.push({ horizon: h.name, start, asOf });
    }
  }
  return windows;
}

function summary(curve) {
  const m = metrics(curve);
  return { total: +m.totalPct.toFixed(3), annual: +m.cagrPct.toFixed(3), dd: +m.maxDDPct.toFixed(3) };
}

const rows = [];
const benchCache = new Map();
const bench = (start, asOf) => {
  const key = `${start}|${asOf}`;
  if (!benchCache.has(key)) {
    const b = summary(benchmarkCurve(data, start, asOf));
    benchCache.set(key, { ...b, market: marketType(b.annual) });
  }
  return benchCache.get(key);
};

const t0 = Date.now();
if (part === "filters") {
  const settings = [];
  for (const pick of PICKS)
    for (const topN of [10, 20])
      for (const rebalance of ["1w", "1m"])
        for (const weights of ["hold", "equal"]) settings.push({ pick, topN, rebalance, weights });
  const all = windowsFrom("2019-01-01");
  const rated = windowsFrom("2023-06-01");
  for (const [i, s] of settings.entries()) {
    for (const w of s.pick.includes("buy") ? rated : all) {
      const r = run(data, { ...s, from: w.start, asOf: w.asOf });
      if (!r.curve.length) continue;
      rows.push({ ...s, ...w, first: r.start, ...summary(r.curve), bench: bench(r.start, w.asOf) });
    }
    if (i % 8 === 7) console.log(`${i + 1}/${settings.length} settings, ${rows.length} rows, ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
} else {
  const bases = [
    { name: "A", topN: 20, rebalance: "1w", weights: "equal" },
    { name: "B", topN: 20, rebalance: "1m", weights: "hold" },
  ];
  const sets = [[], ["R1"], ["R2"], ["R3"], ["R1", "R2"], ["R1", "R3"], ["R2", "R3"], ["R1", "R2", "R3"]];
  const windows = windowsFrom("2019-01-01");
  for (const base of bases) {
    for (const rules of sets) {
      for (const w of windows) {
        const r = runRules(data, { base, rules, from: w.start, asOf: w.asOf });
        rows.push({ base: base.name, rules: rules.join("+") || "none", ...w, first: r.start, ...summary(r.curve), stops: r.stops, offShare: +r.offShare.toFixed(1), bench: bench(r.start, w.asOf) });
      }
      console.log(`${base.name} ${rules.join("+") || "none"}: ${rows.length} rows, ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
  }
} 
writeFileSync(out(`rolling-${part}.json`), JSON.stringify({ end: data.asOf, rows }));
console.log("done", rows.length, ((Date.now() - t0) / 1000).toFixed(0) + "s");
