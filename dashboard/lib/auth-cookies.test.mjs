import assert from "node:assert/strict";
import { test } from "node:test";

import { authCookieNames, expireCookie } from "./auth-cookies.mjs";

test("finds the session cookie and its chunks, nothing else", () => {
  const cookie = "cupel_did=x; sb-abc-auth-token.0=a; theme=dark; sb-abc-auth-token.1=b; sb-abc-auth-token=c";
  assert.deepEqual(authCookieNames(cookie), ["sb-abc-auth-token.0", "sb-abc-auth-token.1", "sb-abc-auth-token"]);
});

test("an empty cookie string has none", () => {
  assert.deepEqual(authCookieNames(""), []);
});

test("expires at the root path", () => {
  assert.equal(expireCookie("sb-abc-auth-token"), "sb-abc-auth-token=; Max-Age=0; path=/; SameSite=Lax");
});
