import assert from "node:assert/strict";
import { test } from "node:test";

import { listing } from "./listing.mjs";

test("a BSE-only symbol reads as its ticker on BSE", () => {
  assert.deepEqual(listing("TANFACIND.BO"), { ticker: "TANFACIND", exchange: "BSE" });
});

test("any other symbol is shown as it is", () => {
  assert.deepEqual(listing("RELIANCE"), { ticker: "RELIANCE", exchange: null });
  assert.deepEqual(listing("BRK-B"), { ticker: "BRK-B", exchange: null });
});
