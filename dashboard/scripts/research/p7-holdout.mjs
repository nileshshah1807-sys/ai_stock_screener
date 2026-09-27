// P7 holdout: the pre-registered rule and its base, once, on the held-out
// year. Needs `data.mjs holdout` first. Writes out/p7-holdout.json.
//
//   node scripts/research/p7-holdout.mjs
import { writeFileSync } from "node:fs";

import { benchmarkCurve, episodes, loadData, metrics, runRules } from "./engine.mjs";
import { out } from "./paths.mjs";

const data = loadData("holdout");
const from = data.dates.find((d) => d >= "2025-10-01");
const base = { topN: 20, rebalance: "1w", weights: "equal" };
const result = {};
for (const rules of [[], ["R2", "R3"]]) {
  const r = runRules(data, { base, rules, from });
  const worst = episodes(r.curve, 3);
  delete r.curve;
  result[rules.join("+") || "none"] = { ...r, worst };
}
const b = metrics(benchmarkCurve(data, result.none.start, data.asOf));
result.nifty = { totalPct: b.totalPct, maxDDPct: b.maxDDPct, through: data.benchmark.at(-1).time };
const A = result.none, C = result["R2+R3"];
const drawdownTest = Math.abs(C.maxDDPct) <= (2 / 3) * Math.abs(A.maxDDPct);
const returnTest = C.totalPct >= b.totalPct;
result.verdict = { firstRanking: from, start: A.start, asOf: data.asOf, drawdownTest, returnTest, adopt: drawdownTest && returnTest };
writeFileSync(out("p7-holdout.json"), JSON.stringify(result, null, 1));
for (const k of ["none", "R2+R3"]) console.log(k.padEnd(6), "total", result[k].totalPct.toFixed(2), "DD", result[k].maxDDPct.toFixed(2));
console.log("Nifty 500", b.totalPct.toFixed(2), b.maxDDPct.toFixed(2), result.verdict);
