import assert from "node:assert/strict";
import test from "node:test";

import { SAMPLE_MARKETS, sampleRows } from "./landing.mjs";

test("the Stage 2 chip keeps only Stage 2 rows", () => {
  for (const market of Object.keys(SAMPLE_MARKETS)) {
    const rows = sampleRows(market, true);
    assert.ok(rows.length > 0 && rows.every((row) => row.stage === 2));
    assert.ok(sampleRows(market, false).length > rows.length);
  }
});

test("an unknown market has no rows rather than throwing", () => {
  assert.deepEqual(sampleRows("xx", false), []);
});
