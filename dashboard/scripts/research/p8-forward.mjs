// P8: the trailing stop against the same basket without it, on published
// rankings from 28 Sep 2026 only. See docs/Review/p8_trailing_stop_forward_preregistration.md.
// Needs `data.mjs holdout` first (it loads published rankings to the latest run).
//
//   node scripts/research/p8-forward.mjs
import { loadData, runRules } from "./engine.mjs";

const data = loadData("holdout");
const START = "2026-09-28";
const published = data.dates.filter((d) => d >= START && d >= data.liveFrom);
if (published.length < 2) {
  console.log(`P8 has not started: no published ranking with a session after it since ${START} (data through ${data.asOf}).`);
  process.exit(0);
}
const base = { topN: 20, rebalance: "1m", weights: "hold" };
const from = published[0];
const plain = runRules(data, { base, rules: [], from });
const stop = runRules(data, { base, rules: ["R3"], from });
const days = (Date.parse(data.asOf) - Date.parse(plain.start)) / 864e5;
console.log(`P8, ${plain.start} to ${data.asOf} (${Math.round(days)} days)`);
console.log(`  base  return ${plain.totalPct.toFixed(2)}%  worst fall ${plain.maxDDPct.toFixed(2)}%`);
console.log(`  stop  return ${stop.totalPct.toFixed(2)}%  worst fall ${stop.maxDDPct.toFixed(2)}%  (${stop.stops} stops)`);
const shallower = stop.maxDDPct - plain.maxDDPct;
const cost = plain.totalPct - stop.totalPct;
console.log(`  fall shallower by ${shallower.toFixed(2)} pts (needs >= 2); return given up ${cost.toFixed(2)} pts (needs <= 5)`);
if (days < 365) console.log("  Before 12 months: information only, no decision.");
else if (plain.maxDDPct > -10) console.log("  The base fell less than 10%: decision deferred 6 months.");
else console.log(`  Decision: ${shallower >= 2 && cost <= 5 ? "adopt" : "do not adopt"} the stop.`);
