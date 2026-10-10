import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_SESSION_MAX_AGE_HOURS,
  isSessionExpired,
  sessionMaxAgeSeconds,
  sessionStartedAt,
} from "./session-policy.mjs";

const HOUR = 3600;
const WEEK = DEFAULT_SESSION_MAX_AGE_HOURS * HOUR;
const SIGNED_IN = 1_800_000_000;

const claimsAt = (...timestamps) => ({
  sub: "user",
  amr: timestamps.map((timestamp) => ({ method: "otp", timestamp })),
});

test("the default lifetime is seven days", () => {
  assert.equal(sessionMaxAgeSeconds(undefined), 7 * 24 * HOUR);
});

test("SESSION_MAX_AGE_HOURS overrides the lifetime, fractions included", () => {
  assert.equal(sessionMaxAgeSeconds("12"), 12 * HOUR);
  assert.equal(sessionMaxAgeSeconds("0.5"), 1800);
});

test("an unusable SESSION_MAX_AGE_HOURS falls back to the default, never to no limit", () => {
  for (const raw of ["", "  ", "0", "-4", "forever", "Infinity", "NaN"]) {
    assert.equal(sessionMaxAgeSeconds(raw), WEEK, `raw=${JSON.stringify(raw)}`);
  }
});

test("a session inside its lifetime is not expired", () => {
  assert.equal(isSessionExpired(claimsAt(SIGNED_IN), SIGNED_IN + WEEK - 1, WEEK), false);
});

test("a session expires at the lifetime boundary", () => {
  assert.equal(isSessionExpired(claimsAt(SIGNED_IN), SIGNED_IN + WEEK, WEEK), true);
  assert.equal(isSessionExpired(claimsAt(SIGNED_IN), SIGNED_IN + 400 * 24 * HOUR, WEEK), true);
});

test("a refreshed token does not restart the clock", () => {
  // iat moves on every refresh; the amr entry is what stays put.
  const refreshed = { ...claimsAt(SIGNED_IN), iat: SIGNED_IN + WEEK + 10 };
  assert.equal(isSessionExpired(refreshed, SIGNED_IN + WEEK + 20, WEEK), true);
});

test("the earliest authentication starts the clock, whatever order the entries are in", () => {
  assert.equal(sessionStartedAt(claimsAt(SIGNED_IN + 500, SIGNED_IN, SIGNED_IN + 900)), SIGNED_IN);
});

test("a token that does not say when it authenticated counts as expired", () => {
  for (const claims of [
    null,
    undefined,
    {},
    { amr: [] },
    { amr: "otp" },
    { amr: [{ method: "otp" }] },
    { amr: [{ method: "otp", timestamp: "soon" }] },
    { amr: [{ method: "otp", timestamp: 0 }] },
  ]) {
    assert.equal(sessionStartedAt(claims), null);
    assert.equal(isSessionExpired(claims, SIGNED_IN, WEEK), true);
  }
});

test("a timestamp that arrives as a numeric string is still read", () => {
  assert.equal(sessionStartedAt({ amr: [{ method: "otp", timestamp: String(SIGNED_IN) }] }), SIGNED_IN);
});
