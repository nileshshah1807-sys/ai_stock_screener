import assert from "node:assert/strict";
import test from "node:test";

import { INVOICE_NAME_MIN, invoiceNameProblem } from "./display-name.mjs";

test("an invoice name needs at least two real characters", () => {
  assert.equal(INVOICE_NAME_MIN, 2);
  assert.equal(invoiceNameProblem("Priya Shah"), null);
  assert.equal(invoiceNameProblem("Al"), null);
  assert.equal(invoiceNameProblem("  Jo  "), null, "trimmed first");
  for (const empty of ["", "   ", "\n\t", null, undefined, "A", " A "]) assert.match(invoiceNameProblem(empty), /at least 2/, JSON.stringify(empty));
});

test("an over-long invoice name is refused, not cut", () => {
  assert.match(invoiceNameProblem("x".repeat(61)), /60 characters or fewer/);
  assert.equal(invoiceNameProblem("x".repeat(60)), null);
});
