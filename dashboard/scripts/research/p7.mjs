// P7 design runs: two bases x every subset of the three rules, into
// out/p7-design.json. See docs/Review/p7_drawdown_rules_preregistration.md.
//
//   node scripts/research/p7.mjs [2025-09-30]
import { writeFileSync } from "node:fs";

import { benchmarkCurve, loadData, metrics, runRules } from "./engine.mjs";
import { out } from "./paths.mjs";

const data = loadData(process.argv[2] ?? "2025-09-30");
const bases = [
  { name: "A", label: "All · Top 20 · weekly · reset to equal", topN: 20, rebalance: "1w", weights: "equal" },
  { name: "B", label: "All · Top 20 · monthly · hold as bought", topN: 20, rebalance: "1m", weights: "hold" },
];
const sets = [[], ["R1"], ["R2"], ["R3"], ["R1", "R2"], ["R1", "R3"], ["R2", "R3"], ["R1", "R2", "R3"]];
const rows = [];
for (const base of bases) {
  for (const rules of sets) {
    const r = runRules(data, { base, rules, from: "2019-01-01" });
    delete r.curve;
    rows.push({ base: base.name, rules: rules.join("+") || "none", ...r });
  }
}
const bench = metrics(benchmarkCurve(data, rows[0].start, data.asOf));
writeFileSync(out("p7-design.json"), JSON.stringify({ bench, out: rows, bases }));
console.log("Nifty 500", bench.cagrPct.toFixed(1), bench.maxDDPct.toFixed(1));
for (const r of rows) console.log(r.base, r.rules.padEnd(9), "CAGR", r.cagrPct.toFixed(1), "DD", r.maxDDPct.toFixed(1), "cash%", r.offShare.toFixed(0), "stops", r.stops);
