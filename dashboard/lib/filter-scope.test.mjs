import assert from "node:assert/strict";
import test from "node:test";

import { narrowsRows } from "./filter-scope.mjs";

test("only a filter that can drop a row counts; sort, page, weights and display do not", () => {
  assert.equal(narrowsRows({}), false);
  assert.equal(narrowsRows({ sort: "custom_score", dir: "desc", page: 3, weights: "q20", hiddenColumns: ["pe"], density: "compact" }), false);
  assert.equal(narrowsRows({ q: "  ", sector: [], ranges: { pe: "" }, hasTranscript: false }), false, "empty values are no filter");
  assert.equal(narrowsRows({ q: "tata" }), true);
  assert.equal(narrowsRows({ sector: ["Energy"] }), true);
  assert.equal(narrowsRows({ ranges: { pe: "0-20" } }), true);
  assert.equal(narrowsRows({ hasTranscript: true }), true);
  assert.equal(narrowsRows({ somethingNew: 1 }), true, "an unknown key is treated as a filter");
});
