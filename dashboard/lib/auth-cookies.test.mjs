import assert from "node:assert/strict";
import { test } from "node:test";

import { authCookieNames, expireCookie } from "./auth-cookies.mjs";

test("finds the session cookie and its chunks, nothing else", () => {
  const cookie = "cupel_did=x; sb-abc-auth-token.0=a; theme=dark; sb-abc-auth-token.1=b; sb-abc-auth-token=c";
  assert.deepEqual(authCookieNames(cookie), ["sb-abc-auth-token.0", "sb-abc-auth-token.1", "sb-abc-auth-token"]);
});

test("a sign-in's code-verifier cookies are not the session", () => {
  assert.deepEqual(authCookieNames("sb-abc-auth-token-code-verifier=v; sb-abc-auth-token-flows-code-verifier=w"), []);
});

test("an empty cookie string has none", () => {
  assert.deepEqual(authCookieNames(""), []);
});

test("expires at the root path", () => {
  assert.equal(expireCookie("sb-abc-auth-token"), "sb-abc-auth-token=; Max-Age=0; path=/; SameSite=Lax");
});
