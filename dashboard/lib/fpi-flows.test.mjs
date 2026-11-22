import assert from "node:assert/strict";
import { test } from "node:test";

import {
  foreignDeals,
  fortnightLabel,
  gridScale,
  heatFill,
  sectorExtremes,
  sectorFlows,
  sectorPageSlug,
} from "./fpi-flows.mjs";

test("each NSDL sector links to its own Sectors page when there is one", () => {
  const pages = ["financial-services", "media-entertainment-publication", "oil-gas-consumable-fuels"];
  assert.equal(sectorPageSlug("Financial Services", pages), "financial-services");
  assert.equal(sectorPageSlug("Media, Entertainment & Publication", pages), "media-entertainment-publication");
  assert.equal(sectorPageSlug("Oil, Gas & Consumable Fuels", pages), "oil-gas-consumable-fuels");
  assert.equal(sectorPageSlug("Others", pages), null);
  assert.equal(sectorPageSlug("Financial Services", ["financial-services-yahoo"]), null);
  assert.equal(sectorPageSlug("Financial Services", null), null);
});

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

test("sector extremes: the latest fortnight's largest buy and sale, none when a side is empty", () => {
  assert.deepEqual(sectorExtremes(rows), {
    start: "2026-11-01",
    end: "2026-11-15",
    bought: { sector: "Financial Services", net: 43102 },
    sold: { sector: "Capital Goods", net: -3781 },
  });
  const allBought = [fortnight("2026-11-01", "2026-11-15", [{ sector: "Realty", net: 5, held: 10 }], {})];
  assert.equal(sectorExtremes(allBought).sold, null);
  assert.equal(sectorExtremes([]), null);
});

test("heat fill: sign picks the hue, a missing figure has none", () => {
  assert.match(heatFill(100, 100), /var\(--positive\) 85%/);
  assert.match(heatFill(-25, 100), /var\(--negative\) 43%/);
  assert.match(heatFill(500, 100), /var\(--positive\) 85%/);
  assert.equal(heatFill(null, 100), "transparent");
});

test("grid scale is the 90th percentile, so one outlier does not wash out the rest", () => {
  const history = [...Array(9).fill(100), 10000];
  assert.equal(gridScale({ sectors: [{ history }] }), 100);
  assert.equal(gridScale({ sectors: [{ history: [null, -883, 43102] }] }), 883);
  assert.equal(gridScale({ sectors: [] }), 1);
});

test("foreign deals keep usable rows only", () => {
  const deals = foreignDeals({
    deals: { bought: [{ symbol: "TDPOWERSYS", net: 500 }, { symbol: "X", net: null }], sold: "bad" },
    deals_since: "2026-10-23",
  });
  assert.deepEqual(deals, { bought: [{ symbol: "TDPOWERSYS", net: 500 }], sold: [], since: "2026-10-23" });
  assert.deepEqual(foreignDeals(null), { bought: [], sold: [], since: null });
});
