// The invested-share study: the unfiltered Top 20 with 100/80/60/40% of the
// money in the basket and the rest held as cash earning nothing, over the
// whole backtest and across rolling windows. Writes out/invested.json.
//
//   node scripts/research/invested.mjs [2026-08-10]
import { writeFileSync } from "node:fs";

import { benchmarkCurve, loadData, metrics, runRules } from "./engine.mjs";
import { out } from "./paths.mjs";

const data = loadData(process.argv[2] ?? "2026-08-10");
const SHARES = [100, 80, 60, 40];
const BASES = [
  { name: "A", label: "Weekly, reset to equal", topN: 20, rebalance: "1w", weights: "equal" },
  { name: "B", label: "Monthly, hold as bought", topN: 20, rebalance: "1m", weights: "hold" },
];
const plusMonths = (date, months) => {
  const t = new Date(`${date}T00:00:00Z`);
  t.setUTCMonth(t.getUTCMonth() + months);
  return t.toISOString().slice(0, 10);
};
const lastSession = (date) => {
  let found = null;
  for (const s of data.sessions) {
    if (s > date) break;
    found = s;
  }
  return found;
};
const seen = new Set();
const starts = data.dates.filter((d) => d >= "2019-01-01" && !seen.has(d.slice(0, 7)) && seen.add(d.slice(0, 7)));
const quantile = (xs, q) => {
  const s = [...xs].sort((a, b) => a - b);
  const i = (s.length - 1) * q;
  return s[Math.floor(i)] + (s[Math.ceil(i)] - s[Math.floor(i)]) * (i - Math.floor(i));
};

const result = { end: data.asOf, full: [], rolling: {} };
for (const base of BASES) {
  for (const investedPct of SHARES) {
    const r = runRules(data, { base: { ...base, investedPct }, rules: [], from: "2019-01-01" });
    const { curve, ...rest } = r;
    result.full.push({ base: base.name, label: base.label, investedPct, ...rest, points: curve.filter((_, i) => i % 3 === 0).map((p) => [p.time, +p.value.toFixed(2)]) });
  }
}
result.bench = metrics(benchmarkCurve(data, result.full[0].start, data.asOf));

for (const months of [12, 36]) {
  const rows = [];
  for (const start of starts) {
    const stop = plusMonths(start, months);
    if (stop > data.asOf) continue;
    const asOf = lastSession(stop);
    const bench = metrics(benchmarkCurve(data, start, asOf));
    for (const base of BASES) {
      for (const investedPct of SHARES) {
        const r = runRules(data, { base: { ...base, investedPct }, rules: [], from: start, asOf });
        rows.push({ base: base.name, investedPct, start, annual: r.cagrPct, dd: r.maxDDPct, benchAnnual: bench.cagrPct, benchDD: bench.maxDDPct });
      }
    }
  }
  result.rolling[months] = BASES.flatMap((base) => SHARES.map((investedPct) => {
    const own = rows.filter((r) => r.base === base.name && r.investedPct === investedPct);
    return {
      base: base.name, investedPct, windows: own.length,
      medAnnual: quantile(own.map((r) => r.annual), 0.5), p10Annual: quantile(own.map((r) => r.annual), 0.1),
      medDD: quantile(own.map((r) => r.dd), 0.5), worstDD: Math.min(...own.map((r) => r.dd)),
      ddPast20: (own.filter((r) => r.dd < -20).length / own.length) * 100,
      beatNifty: (own.filter((r) => r.annual > r.benchAnnual).length / own.length) * 100,
      niftyMedDD: quantile(own.map((r) => r.benchDD), 0.5),
    };
  }));
}
writeFileSync(out("invested.json"), JSON.stringify(result));
console.log("Nifty 500", result.bench.cagrPct.toFixed(1), result.bench.maxDDPct.toFixed(1));
for (const r of result.full) console.log(r.base, String(r.investedPct).padStart(3) + "%", "CAGR", r.cagrPct.toFixed(1), "DD", r.maxDDPct.toFixed(1), "calmar", r.calmar.toFixed(2));
for (const [m, rs] of Object.entries(result.rolling)) {
  console.log(`-- ${m}-month windows`);
  for (const r of rs) console.log(r.base, String(r.investedPct).padStart(3) + "%", "n", r.windows, "medAnn", r.medAnnual.toFixed(1), "p10", r.p10Annual.toFixed(1), "medDD", r.medDD.toFixed(1), "worstDD", r.worstDD.toFixed(1), ">-20%", r.ddPast20.toFixed(0) + "%", "beatNifty", r.beatNifty.toFixed(0) + "%");
}
