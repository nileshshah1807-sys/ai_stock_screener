import assert from "node:assert/strict";
import { test } from "node:test";

import { csvCell } from "./csv.mjs";

test("text that starts like a formula is quoted so a spreadsheet shows it as text", () => {
  for (const text of ["=HYPERLINK(\"x\")", "+1+1", "-cmd", "@SUM(A1)", "\tx", "\rx"]) {
    assert.ok(csvCell(text).replace(/^"/, "").startsWith("'"), text);
  }
  assert.equal(csvCell("=1+1"), "'=1+1");
});

test("numbers stay numbers, negative ones too", () => {
  assert.equal(csvCell(-12.5), "-12.5");
  assert.equal(csvCell(0), "0");
  assert.equal(csvCell("-12.5"), "-12.5");
  assert.equal(csvCell("1e-7"), "1e-7");
});

test("ordinary cells keep their RFC 4180 escaping", () => {
  assert.equal(csvCell(null), "");
  assert.equal(csvCell("Tata, Sons"), '"Tata, Sons"');
  assert.equal(csvCell('He said "hi"'), '"He said ""hi"""');
  assert.equal(csvCell("=a,b"), "\"'=a,b\"");
});
