import assert from "node:assert/strict";
import { test } from "node:test";

import { foreignDeals, fortnightLabel, gridScale, heatFill, sectorFlows } from "./fpi-flows.mjs";

const fortnight = (start, end, sectors, total) => ({ period_start: start, period_end: end, sectors, total });
const rows = [
  fortnight("2026-11-01", "2026-11-15", [
    { sector: "Financial Services", net: 43102, held: 2262071 },
    { sector: "Capital Goods", net: -3781, held: 470287 },
    { sector: "Sovereign", net: 0, held: 0 },
  ], { net: 84291, held: 7168672 }),
  fortnight("2026-10-16", "2026-10-31", [
    { sector: "Financial Services", net: -883, held: 1962000 },
  ], { net: 13112, held: 6525808 }),
];

test("fortnight labels", () => {
  assert.equal(fortnightLabel("2026-11-01", "2026-11-15"), "1–15 Nov 2026");
  assert.equal(fortnightLabel("2026-10-16", "2026-10-31"), "16–31 Oct 2026");
  assert.equal(fortnightLabel(null, "2026-10-31"), "—");
});

test("sector table: latest first by net, history oldest first, a missing sector stays missing", () => {
  const table = sectorFlows(rows, { history: 12, year: 24 });
  assert.deepEqual(table.latest, { start: "2026-11-01", end: "2026-11-15" });
  assert.deepEqual(table.sectors.map((s) => s.sector), ["Financial Services", "Capital Goods"]);
  assert.deepEqual(table.sectors[0].history, [-883, 43102]);
  assert.deepEqual(table.sectors[1].history, [null, -3781]);
  assert.equal(table.sectors[0].year, 42219);
  assert.equal(table.sectors[1].year, -3781);
  assert.deepEqual(table.total.history, [13112, 84291]);
  assert.equal(table.yearSpan, 2);
});

test("history and year windows count fortnights from the latest", () => {
  const table = sectorFlows(rows, { history: 1, year: 1 });
  assert.deepEqual(table.sectors[0].history, [43102]);
  assert.equal(table.sectors[0].year, 43102);
});

test("no fortnights is no table", () => {
  assert.equal(sectorFlows([]), null);
  assert.equal(sectorFlows(undefined), null);
});

test("heat fill: sign picks the hue, a missing figure has none", () => {
  assert.match(heatFill(100, 100), /var\(--positive\) 72%/);
  assert.match(heatFill(-25, 100), /var\(--negative\) 36%/);
  assert.equal(heatFill(null, 100), "transparent");
  assert.equal(gridScale(sectorFlows(rows)), 43102);
});

test("foreign deals keep usable rows only", () => {
  const deals = foreignDeals({
    deals: { bought: [{ symbol: "TDPOWERSYS", net: 500 }, { symbol: "X", net: null }], sold: "bad" },
    deals_since: "2026-10-23",
  });
  assert.deepEqual(deals, { bought: [{ symbol: "TDPOWERSYS", net: 500 }], sold: [], since: "2026-10-23" });
  assert.deepEqual(foreignDeals(null), { bought: [], sold: [], since: null });
});
