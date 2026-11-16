import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { oauthRedirectTo, oneTapLanding, oneTapNonce } from "./google-sign-in.mjs";

test("the button lands on the callback with a same-origin next only", () => {
  assert.equal(oauthRedirectTo("https://cupel.in", "/ind/results"), "https://cupel.in/auth/callback?next=%2Find%2Fresults");
  assert.equal(oauthRedirectTo("https://cupel.in", "https://evil.example"), "https://cupel.in/auth/callback?next=%2Fscreener");
  assert.equal(oauthRedirectTo("https://cupel.in", null), "https://cupel.in/auth/callback?next=%2Fscreener");
});

test("One Tap lands on the callback's guard step", () => {
  assert.equal(oneTapLanding("/us/screener"), "/auth/callback?via=one_tap&next=%2Fus%2Fscreener");
  assert.equal(oneTapLanding("//evil.example"), "/auth/callback?via=one_tap&next=%2Fscreener");
});

test("the nonce Google gets is the SHA-256 of the one Supabase gets", async () => {
  const { raw, hashed } = await oneTapNonce();
  assert.match(raw, /^[0-9a-f]{64}$/);
  assert.equal(hashed, createHash("sha256").update(raw).digest("hex"));
  assert.notEqual((await oneTapNonce()).raw, raw);
});
