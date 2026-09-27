// The filter study: every pick x basket size x rebalance x weighting on the
// design period, then every figure the report quotes, into out/facts.json.
//
//   node scripts/research/filter-study.mjs [2025-09-30]
import { writeFileSync } from "node:fs";

import { benchmarkCurve, episodes, loadData, metrics, PICKS, run } from "./engine.mjs";
import { out } from "./paths.mjs";

const data = loadData(process.argv[2] ?? "2025-09-30");
const med = (xs) => {
  const s = xs.filter((x) => x != null).sort((a, b) => a - b);
  if (!s.length) return null;
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const strip = (row) => {
  const copy = { ...row };
  delete copy.curve;
  return copy;
};

// Rating picks exist only from May 2023, so they are compared on that window.
const windows = [
  { name: "full", from: "2019-01-01", ratings: false },
  { name: "rated", from: "2023-05-26", ratings: true },
];
const facts = { asOf: data.asOf, windows: {} };
for (const win of windows) {
  const rows = [];
  for (const pick of PICKS) {
    if (!win.ratings && pick.includes("buy")) continue;
    for (const topN of [10, 20, 50])
      for (const rebalance of ["never", "1w", "2w", "1m", "3m"])
        for (const weights of rebalance === "never" ? ["hold"] : ["hold", "equal"])
          rows.push(run(data, { pick, topN, rebalance, weights, from: win.from }));
  }
  const start = rows[0].start;
  const bench = metrics(benchmarkCurve(data, start, data.asOf));
  const byPick = [...new Set(rows.map((r) => r.pick))].map((pick) => {
    const rs = rows.filter((r) => r.pick === pick);
    return {
      pick, n: rs.length, medCagr: med(rs.map((r) => r.cagrPct)), medDD: med(rs.map((r) => r.maxDDPct)),
      bestDD: Math.max(...rs.map((r) => r.maxDDPct)), medCalmar: med(rs.map((r) => r.calmar)),
      medWin: med(rs.map((r) => r.winRate)), medShortShare: med(rs.map((r) => r.shortRounds / r.rounds)) * 100,
      beatShare: (rs.filter((r) => r.cagrPct > bench.cagrPct).length / rs.length) * 100,
    };
  });
  const effect = (key) => [...new Set(rows.map((r) => r[key]))].map((value) => {
    const rs = rows.filter((r) => r[key] === value);
    return { value, n: rs.length, medCagr: med(rs.map((r) => r.cagrPct)), medDD: med(rs.map((r) => r.maxDDPct)), medCalmar: med(rs.map((r) => r.calmar)) };
  });
  // Hold against reset for the same pick, size and frequency.
  const paired = rows.filter((r) => r.weights === "equal").map((e) => {
    const h = rows.find((r) => r.weights === "hold" && r.pick === e.pick && r.topN === e.topN && r.rebalance === e.rebalance);
    return { dCagr: e.cagrPct - h.cagrPct, dDD: e.maxDDPct - h.maxDDPct };
  });
  facts.windows[win.name] = {
    start, n: rows.length,
    bench: { cagrPct: bench.cagrPct, maxDDPct: bench.maxDDPct, totalPct: bench.totalPct, sharpe: bench.sharpe, byYear: bench.byYear },
    byPick, effects: { topN: effect("topN"), rebalance: effect("rebalance"), weights: effect("weights") },
    pairedEqualMinusHold: { n: paired.length, medDCagr: med(paired.map((p) => p.dCagr)), medDDD: med(paired.map((p) => p.dDD)), equalBetterCagr: paired.filter((p) => p.dCagr > 0).length },
    withinCap: rows.filter((r) => r.maxDDPct >= -20).sort((a, b) => b.cagrPct - a.cagrPct).map(strip),
    top: [...rows].sort((a, b) => b.cagrPct - a.cagrPct).slice(0, 10).map(strip),
    scatter: rows.map((r) => ({ pick: r.pick, topN: r.topN, rebalance: r.rebalance, weights: r.weights, cagr: r.cagrPct, dd: r.maxDDPct })),
  };
}

// Drawdown anatomy and curves for reference settings over the full window.
const refs = [
  { pick: "all", topN: 20, rebalance: "1m", weights: "hold" },
  { pick: "all", topN: 10, rebalance: "1w", weights: "hold" },
  { pick: "stage2", topN: 20, rebalance: "1w", weights: "hold" },
  { pick: "fresh_stage2", topN: 20, rebalance: "1w", weights: "hold" },
];
const bc = benchmarkCurve(data, "2018-12-31", data.asOf);
const levelAt = (t) => {
  let v = null;
  for (const p of bc) {
    if (p.time > t) break;
    v = 1 + p.value / 100;
  }
  return v;
};
facts.refs = refs.map((cfg) => {
  const r = run(data, { ...cfg, from: "2019-01-01" });
  const thin = r.curve.filter((_, i) => i % 3 === 0 || i === r.curve.length - 1);
  return {
    ...strip(r), curve: thin.map((p) => [p.time, +p.value.toFixed(2)]),
    episodes: episodes(r.curve, 4).map((e) => ({ ...e, bench: (levelAt(e.trough) / levelAt(e.peak) - 1) * 100 })),
  };
});
facts.benchCurve = bc.filter((_, i) => i % 3 === 0).map((p) => [p.time, +p.value.toFixed(2)]);
writeFileSync(out("facts.json"), JSON.stringify(facts, null, 1));
for (const w of Object.keys(facts.windows)) {
  console.log(w, facts.windows[w].n, "runs; median CAGR by pick:",
    facts.windows[w].byPick.map((p) => `${p.pick} ${p.medCagr.toFixed(1)}`).join(", "));
}
