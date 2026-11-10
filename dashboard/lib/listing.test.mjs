import assert from "node:assert/strict";
import { test } from "node:test";

import { listing } from "./listing.mjs";

test("a BSE-only symbol reads as its ticker on BSE", () => {
  assert.deepEqual(listing("TANFACIND.BO"), { ticker: "TANFACIND", exchange: "BSE", sme: false });
});

test("any other symbol is shown as it is", () => {
  assert.deepEqual(listing("RELIANCE"), { ticker: "RELIANCE", exchange: null, sme: false });
  assert.deepEqual(listing("BRK-B"), { ticker: "BRK-B", exchange: null, sme: false });
});

test("an SME is flagged on either exchange", () => {
  assert.equal(listing("ANAWIL", true).sme, true);
  assert.deepEqual(listing("XYZ.BO", true), { ticker: "XYZ", exchange: "BSE", sme: true });
});
