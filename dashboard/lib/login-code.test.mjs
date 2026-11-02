import assert from "node:assert/strict";
import test from "node:test";

import { isCode, normalizeCode, otpTypeOf, safeNext } from "./login-code.mjs";

test("a pasted code is reduced to its digits", () => {
  assert.equal(normalizeCode(" 123 456\n"), "123456");
  assert.equal(normalizeCode("12-34-56"), "123456");
  assert.equal(normalizeCode(null), "");
});
test("only six digits is a code", () => {
  assert.ok(isCode("123 456"));
  assert.ok(!isCode("12345"));
  assert.ok(!isCode("1234567"));
  assert.ok(!isCode("abcdef"));
});
test("unknown link types fall back to email", () => {
  assert.equal(otpTypeOf("magiclink"), "magiclink");
  assert.equal(otpTypeOf("bogus"), "email");
  assert.equal(otpTypeOf(null), "email");
});
test("next stays on this site", () => {
  assert.equal(safeNext("/ind/results"), "/ind/results");
  assert.equal(safeNext("//evil.example"), "/");
  assert.equal(safeNext("/\\evil.example"), "/");
  assert.equal(safeNext("https://evil.example"), "/");
  assert.equal(safeNext(undefined), "/");
});
