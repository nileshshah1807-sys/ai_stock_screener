import assert from "node:assert/strict";
import test from "node:test";

import { decodeSymbolParam } from "./symbol.mjs";

test("an encoded ampersand symbol is decoded", () => {
  assert.equal(decodeSymbolParam("M%26M"), "M&M");
  assert.equal(decodeSymbolParam("GVT%26D"), "GVT&D");
  assert.equal(decodeSymbolParam("J%26KBANK"), "J&KBANK");
});

test("decoding is idempotent, so an already-decoded symbol is untouched", () => {
  // This is what makes the fix safe on a host that decodes for us.
  for (const symbol of ["M&M", "GVT&D", "ARVIND", "BAJAJ-AUTO", "NAM-INDIA"]) {
    assert.equal(decodeSymbolParam(symbol), symbol);
    assert.equal(decodeSymbolParam(decodeSymbolParam(symbol)), symbol);
  }
});

test("a malformed escape falls back to the raw segment", () => {
  // decodeURIComponent throws on a lone '%'; a 404 is better than a 500.
  assert.equal(decodeSymbolParam("100%"), "100%");
  assert.equal(decodeSymbolParam("%E0%A4"), "%E0%A4");
});

test("a non-string is not passed through to the query", () => {
  assert.equal(decodeSymbolParam(undefined), "");
  assert.equal(decodeSymbolParam(null), "");
});
