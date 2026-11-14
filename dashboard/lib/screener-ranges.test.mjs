import assert from "node:assert/strict";
import test from "node:test";

import { RANGES, columnBounds, formatRange, parseRange, rangeLabel, readRanges } from "./screener-ranges.mjs";

const range = (key) => RANGES.find((item) => item.key === key);

test("a range parses either side alone and round-trips", () => {
  assert.deepEqual(parseRange("10~25"), { min: 10, max: 25 });
  assert.deepEqual(parseRange("~25"), { max: 25 });
  assert.deepEqual(parseRange("1000~"), { min: 1000 });
  assert.deepEqual(parseRange("-15~"), { min: -15 });
  assert.equal(parseRange("~"), null);
  assert.equal(parseRange("abc~x"), null);
  assert.equal(formatRange({ min: 10 }), "10~");
  assert.equal(formatRange({}), "");
  assert.deepEqual(parseRange(formatRange({ min: 0, max: 15 })), { min: 0, max: 15 });
});

test("an old single-bound key reads as the range's minimum, the new key wins", () => {
  const get = (params) => (key) => new URLSearchParams(params).get(key);
  assert.deepEqual(readRanges(get("minCapCr=1000")).cap, { min: 1000 });
  assert.deepEqual(readRanges(get("minQuality=70")).pq, { min: 70 });
  assert.deepEqual(readRanges(get("minCapCr=1000&cap=~500")).cap, { max: 500 });
  assert.deepEqual(Object.keys(readRanges(get("sort=pe_ratio"))), []);
});

test("bounds are converted into the column's own unit", () => {
  // Market cap is stored in rupees and typed in crore.
  assert.deepEqual(columnBounds(range("cap"), { min: 1000 }, 1e7), { min: 1e10, max: undefined });
  // ROE is a stored fraction, typed as a percent.
  assert.deepEqual(columnBounds(range("roe"), { min: 15 }, 1e7), { min: 0.15, max: undefined });
  // Debt to equity is a stored percent, typed as a multiple.
  assert.deepEqual(columnBounds(range("de"), { max: 0.5 }, 1e7), { min: undefined, max: 50 });
  assert.deepEqual(columnBounds(range("pe"), { min: 0, max: 25 }, 1e7), { min: 0, max: 25 });
});

test("every range names a distinct key and a column", () => {
  const keys = RANGES.map((item) => item.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const item of RANGES) assert.ok(item.column && item.label, item.key);
});

test("chip labels read as the filter", () => {
  assert.equal(rangeLabel(range("cap"), { min: 1000 }, "Cr"), "Market cap ≥ 1,000 Cr");
  assert.equal(rangeLabel(range("pe"), { min: 0, max: 25 }, "Cr"), "P/E 0×–25×");
  assert.equal(rangeLabel(range("pq"), { min: 70 }, "Cr"), "Quality ≥ P70");
  assert.equal(rangeLabel(range("roe"), { max: 30 }, "Cr"), "Return on equity ≤ 30%");
});
