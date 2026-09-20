import assert from "node:assert/strict";
import test from "node:test";

import { resolveLogoDomain } from "./logo-domain.mjs";

test("registered .bank.in domains resolve to the bank's own logo domain", () => {
  assert.equal(resolveLogoDomain("hdfc.bank.in"), "hdfcbank.com");
  assert.equal(resolveLogoDomain("icici.bank.in"), "icicibank.com");
  assert.equal(resolveLogoDomain("sbi.bank.in"), "sbi.co.in");
  assert.equal(resolveLogoDomain("kotak.bank.in"), "kotak.com");
  assert.equal(resolveLogoDomain("yes.bank.in"), "yesbank.in");
});

test("distinct banks never share a resolved domain", () => {
  const banks = [
    "hdfc.bank.in",
    "icici.bank.in",
    "sbi.bank.in",
    "axis.bank.in",
    "kotak.bank.in",
    "yes.bank.in",
  ].map(resolveLogoDomain);

  assert.equal(new Set(banks).size, banks.length);
});

test("an unmapped .bank.in domain is dropped rather than collapsed onto bank.in", () => {
  // Brandfetch reduces any unknown `X.bank.in` to `bank.in`, which it serves as
  // YES BANK. Returning null makes the caller draw its own symbol lettermark.
  assert.equal(resolveLogoDomain("somenewbank.bank.in"), null);
  assert.equal(resolveLogoDomain("bank.in"), null);
  assert.equal(resolveLogoDomain("BANK.IN"), null);
});

test("ordinary domains pass through normalized", () => {
  assert.equal(resolveLogoDomain("www.HDFCBank.com"), "hdfcbank.com");
  assert.equal(resolveLogoDomain("  tcs.com  "), "tcs.com");
  assert.equal(resolveLogoDomain("cv.tatamotors.com"), "cv.tatamotors.com");
  assert.equal(resolveLogoDomain("gayatri.co.in"), "gayatri.co.in");
});

test("unusable values yield no logo request", () => {
  assert.equal(resolveLogoDomain(null), null);
  assert.equal(resolveLogoDomain(undefined), null);
  assert.equal(resolveLogoDomain(""), null);
  assert.equal(resolveLogoDomain("   "), null);
  assert.equal(resolveLogoDomain("localhost"), null);
  assert.equal(resolveLogoDomain("not a domain"), null);
});
